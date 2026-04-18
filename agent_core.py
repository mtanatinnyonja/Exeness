"""
Agent IA de trading autonome.

Architecture: Observation → Raisonnement en chaîne (CoT) → Décision
Le LLM est le décideur principal, pas un simple validateur.
Si le LLM est indisponible, l'agent attend — pas de fallback automatique.
"""

import json
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional
from urllib.parse import urlparse

try:
    import requests
except ImportError:
    requests = None

from settings import (
    LOCAL_LLM_ENDPOINT, LOCAL_LLM_MODEL, LOCAL_LLM_TIMEOUT,
    LLM_TEMPERATURE, LLM_MIN_CONFIDENCE,
    MAX_LLM_CALLS_PER_DAY, DAILY_TOKEN_BUDGET,
    ONLY_ALLOW_LOCAL_LLM, PRIMARY_TIMEFRAME, CONFIRM_TIMEFRAME,
    DAILY_LOSS_LIMIT,
)
from signal_engine import (
    calculate_signal_score, build_price_action_description, _MIN_CANDLES,
)
from market_protection import run_all_protections
from smart_strategies import (
    get_session_score, calculate_htf_bias, get_smart_money_context,
    build_strategies_context, check_correlation_risk,
)
from economic_calendar import EconomicCalendar
from runtime_db import RuntimeStore


SYSTEM_PROMPT = """Agent trading MT5. Raisonne puis décide.
Règles: structure claire sinon WAIT, SL derrière niveau structurel, RR>=1.5, doute=WAIT.
JSON uniquement: {"thinking":"...","decision":"BUY|SELL|WAIT","confidence":0.0-1.0,"stop_loss_pips":N,"take_profit_pips":N,"reasoning":"court"}"""


class TradingAgent:
    """
    Agent de trading autonome avec raisonnement en chaîne.
    Observe le marché → Raisonne → Décide.
    """

    def __init__(self, broker, memory, store):
        self.broker = broker
        self.memory = memory
        self.store = store
        self.calendar = EconomicCalendar()
        self.provider = "ollama"

        # State for dashboard / debug
        self.last_prompt = ""
        self.last_raw_response = ""
        self.last_parsed_response = None
        self.last_analysis_instrument = ""
        self.last_analysis_timestamp = ""

        self._load_settings()

    def _load_settings(self):
        settings = self.store.get_settings()
        self.model = str(settings.get("local_llm_model", LOCAL_LLM_MODEL)).strip()
        self.endpoint = str(settings.get("local_llm_endpoint", LOCAL_LLM_ENDPOINT)).strip()
        self.timeout = int(settings.get("local_llm_timeout", LOCAL_LLM_TIMEOUT))
        self.temperature = float(settings.get("llm_temperature", LLM_TEMPERATURE))
        self.min_confidence = float(settings.get("llm_min_confidence", LLM_MIN_CONFIDENCE))
        self.max_calls = int(settings.get("max_llm_calls_per_day", MAX_LLM_CALLS_PER_DAY))
        self.token_budget = int(settings.get("daily_token_budget", DAILY_TOKEN_BUDGET))

    # ═══════════════════════════════════════════════════════════════════
    # PUBLIC API
    # ═══════════════════════════════════════════════════════════════════

    def analyze(self, instrument: str, account: Dict, open_positions: List[Dict]) -> Optional[Dict]:
        """
        Analyse complète d'un instrument.
        Gather context → Reason (CoT) → Decide.
        """
        self._load_settings()
        self.last_analysis_instrument = instrument
        self.last_analysis_timestamp = datetime.now(timezone.utc).isoformat()

        # Step 1: OBSERVE — gather all market context
        ctx = self._gather_context(instrument, account, open_positions)
        if ctx is None:
            return self._wait("Données insuffisantes pour analyser")

        # Step 2: Check hard blocks (no LLM needed)
        if ctx["protections"]["blocked"]:
            blocks = ctx["protections"]["hard_blocks"]
            reason = "; ".join(blocks)
            self.memory.log_session(f"🛡️ {instrument}: bloqué — {reason}")
            return self._wait(f"Bloqué: {reason}")

        # Step 3: Log context summary
        signal = ctx["signal"]
        details = signal.get("details", {})
        self.memory.log_session(
            f"📊 {instrument}: score={signal['score']}/5 dir={signal.get('direction', 'WAIT')} "
            f"regime={details.get('market_regime', '?')} spread={ctx['spread']:.1f}p"
        )
        session = ctx["session"]
        self.memory.log_session(f"🕐 {instrument}: {session['label']} (qualité={session['instrument_quality']})")

        strategies = ctx["strategies"]
        conf = strategies["confluence"]
        self.memory.log_session(
            f"🎯 {instrument}: Confluence={conf['confluence_score']}/{conf['max_score']} "
            f"({conf['quality']}) | HTF={strategies['htf_bias'].get('combined_bias', '?')}"
        )

        if ctx["protections"]["warnings"]:
            for w in ctx["protections"]["warnings"][:3]:
                self.memory.log_session(f"🔎 {instrument}: {w}")

        if ctx["learning"]["reasons"]:
            self.memory.log_session(f"🧠 {instrument}: mémoire → {', '.join(ctx['learning']['reasons'])}")
            if ctx["learning"]["blocked"]:
                self.memory.log_session(f"🛡️ {instrument}: setup bloqué par la mémoire")
                return self._wait("Setup bloqué par la mémoire locale")

        # Step 4: THINK — build prompt and call LLM
        prompt = self._build_cot_prompt(instrument, ctx)
        self.last_prompt = prompt

        raw = self._call_ollama(prompt, instrument)
        if raw is None:
            self.memory.log_session(f"⏸️ {instrument}: LLM indisponible — WAIT")
            return self._wait("LLM indisponible — pas de trade sans analyse")

        self.last_raw_response = raw

        # Step 5: Parse decision from reasoning
        decision = self._parse_decision(raw, ctx)
        self.last_parsed_response = decision

        self.memory.log_session(
            f"🤖 {self.provider} → {instrument}: {decision['decision']} "
            f"(conf: {decision.get('confidence', 0):.2f}) | {decision.get('reasoning', '')[:200]}"
        )

        thinking = decision.get("thinking", "")
        if thinking:
            self.memory.log_session(f"💭 {instrument}: {thinking[:300]}")

        # Step 6: VALIDATE — safety checks
        decision = self._validate(instrument, decision, ctx)

        # Attach context for orchestrator
        decision["signal"] = signal
        decision["spread"] = ctx["spread"]

        return decision

    def get_last_exchange(self) -> Dict:
        return {
            "instrument": self.last_analysis_instrument,
            "timestamp": self.last_analysis_timestamp,
            "prompt": self.last_prompt,
            "raw_response": self.last_raw_response,
            "parsed_response": self.last_parsed_response,
            "provider": self.provider,
            "model": self.model,
        }

    # ═══════════════════════════════════════════════════════════════════
    # CONTEXT GATHERING
    # ═══════════════════════════════════════════════════════════════════

    def _gather_context(self, instrument: str, account: Dict, open_positions: List[Dict]) -> Optional[Dict]:
        """Gather ALL market data upfront for one instrument."""
        candles_needed = max(120, _MIN_CANDLES + 10)
        candles_h1 = self.broker.get_candles(instrument, PRIMARY_TIMEFRAME, candles_needed)

        if len(candles_h1) < _MIN_CANDLES:
            self.memory.log_session(
                f"⚠️ {instrument}: données insuffisantes ({len(candles_h1)}/{_MIN_CANDLES})"
            )
            return None

        candles_m15 = self.broker.get_candles(instrument, CONFIRM_TIMEFRAME, 80)

        # Technical analysis
        signal = calculate_signal_score(candles_h1, instrument)
        signal_confirm = None
        if len(candles_m15) >= 30:
            signal_confirm = calculate_signal_score(candles_m15, instrument)
            # Boost score if both TFs agree
            if signal_confirm["direction"] == signal["direction"] and signal_confirm["score"] >= 2:
                signal["score"] = min(6, signal["score"] + 1)

        # Price action description for LLM
        price_action = build_price_action_description(candles_h1, instrument)

        # Spread
        spread = self.broker.get_spread_pips(instrument)

        # Protections
        pip_size = self.broker._pip_size(instrument)
        protections = run_all_protections(
            instrument, candles_h1, spread, pip_size,
            price=candles_h1[-1]["close"],
        )

        # Session
        session = get_session_score(instrument)

        # HTF bias + SMC + confluence
        try:
            candles_h4 = self.broker.get_candles(instrument, "H4", 60)
            candles_d1 = self.broker.get_candles(instrument, "D1", 30)
        except Exception:
            candles_h4, candles_d1 = [], []

        strategies = build_strategies_context(
            instrument, candles_h1, candles_h4, candles_d1,
            signal_direction=signal.get("direction"),
            signal_score=signal.get("score", 0),
            open_positions=open_positions,
        )

        # Memory assessment
        learning = self.memory.assess_setup(instrument, signal)

        # News
        try:
            news_ctx = self.calendar.get_context_for_llm(instrument)
        except Exception:
            news_ctx = ""

        today_pnl = self.memory.get_daily_pnl()

        return {
            "candles_h1": candles_h1,
            "signal": signal,
            "signal_confirm": signal_confirm,
            "price_action": price_action,
            "spread": spread,
            "pip_size": pip_size,
            "protections": protections,
            "session": session,
            "strategies": strategies,
            "learning": learning,
            "news_ctx": news_ctx,
            "account": account,
            "today_pnl": today_pnl,
            "open_positions": open_positions,
        }

    # ═══════════════════════════════════════════════════════════════════
    # CHAIN-OF-THOUGHT PROMPT
    # ═══════════════════════════════════════════════════════════════════

    def _build_cot_prompt(self, instrument: str, ctx: Dict) -> str:
        signal = ctx["signal"]
        details = signal.get("details", {})
        strategies = ctx["strategies"]
        prot = ctx["protections"]
        session = ctx["session"]
        learning = ctx["learning"]
        account = ctx["account"]

        # TF confirmation
        confirm_text = ""
        if ctx["signal_confirm"]:
            sc = ctx["signal_confirm"]
            if sc["direction"] == signal["direction"] and sc["score"] >= 2:
                confirm_text = f"✅ {CONFIRM_TIMEFRAME} confirme: {sc['direction']} score {sc['score']}/5"
            else:
                confirm_text = f"⚠️ {CONFIRM_TIMEFRAME} non aligné: {sc.get('direction', 'WAIT')} score {sc['score']}/5"

        # Memory
        memory_text = ""
        if learning["reasons"]:
            memory_text = f"Mem: {', '.join(learning['reasons'])}. Risque x{learning['risk_multiplier']:.2f}."

        # Protections (compact)
        prot_text = " | ".join(prot["warnings"][:3]) if prot["warnings"] else "OK"

        # Truncate verbose sections to keep prompt under ~1500 chars
        pa_text = ctx["price_action"]
        if len(pa_text) > 800:
            pa_text = pa_text[:800] + "..."

        strat_text = strategies['llm_context']
        if len(strat_text) > 600:
            strat_text = strat_text[:600] + "..."

        return f"""{instrument} | Score:{signal['score']}/5 Dir:{signal.get('direction','WAIT')} Regime:{details.get('market_regime','?')}
RSI:{details.get('rsi',50):.0f} Spread:{ctx['spread']:.1f}p ATR:{signal.get('atr_pips',0)}p
Supp:{details.get('support',0)} Res:{details.get('resistance',0)} RR_buy:{details.get('rr_buy',0)} RR_sell:{details.get('rr_sell',0)}
{confirm_text}

PRICE ACTION:
{pa_text}

MTF/SMC:
{strat_text}

Protections: {prot_text}
News: {ctx['news_ctx'] or 'aucun'}
Balance:{account.get('balance',0):.0f}$ PnL:{ctx['today_pnl']:.2f}$ Pos:{len(ctx['open_positions'])} {memory_text}

JSON:{{"thinking":"...","decision":"BUY|SELL|WAIT","confidence":0.0-1.0,"stop_loss_pips":N,"take_profit_pips":N,"reasoning":"court"}}"""

    # ═══════════════════════════════════════════════════════════════════
    # LLM COMMUNICATION
    # ═══════════════════════════════════════════════════════════════════

    def _is_local_endpoint(self, url: str) -> bool:
        try:
            parsed = urlparse(url)
            return parsed.hostname in {"127.0.0.1", "localhost"}
        except Exception:
            return False

    def _can_call(self, prompt_tokens: int = 0) -> bool:
        if self.max_calls > 0 and self.memory.get_llm_calls_today() >= self.max_calls:
            return False
        if self.token_budget <= 0:
            return True
        usage = self.memory.get_token_usage_today()
        used = usage["prompt_tokens"] + usage["completion_tokens"]
        return (used + prompt_tokens) < self.token_budget

    def _approx_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)

    def _call_ollama(self, prompt: str, instrument: str) -> Optional[str]:
        if requests is None:
            self.memory.record_error("agent", "package requests absent")
            return None
        if ONLY_ALLOW_LOCAL_LLM and not self._is_local_endpoint(self.endpoint):
            self.memory.record_error("agent", f"endpoint non-local refusé: {self.endpoint}")
            return None

        tokens = self._approx_tokens(prompt)
        if not self._can_call(tokens):
            self.memory.record_error("agent", "budget LLM épuisé")
            return None

        try:
            self.memory.increment_llm_calls()
            self.memory.record_token_usage(prompt_tokens=tokens, completion_tokens=0)

            full_prompt = SYSTEM_PROMPT + "\n\n" + prompt

            response = requests.post(
                self.endpoint,
                headers={"Content-Type": "application/json"},
                json={
                    "model": self.model,
                    "prompt": full_prompt,
                    "stream": False,
                    "options": {
                        "temperature": self.temperature,
                        "num_predict": 200,
                    },
                    "keep_alive": "10m",
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
            raw = (data.get("response") or "").strip()

            completion_tokens = self._approx_tokens(raw)
            self.memory.record_token_usage(prompt_tokens=0, completion_tokens=completion_tokens)

            if not raw:
                self.memory.record_error("agent", "réponse vide du LLM")
                return None

            # Store insight
            if raw:
                try:
                    parsed = self._extract_json(raw)
                    if parsed and parsed.get("insight"):
                        self.memory.add_ai_insight(f"{instrument}: {parsed['insight']}")
                except Exception:
                    pass

            return raw

        except Exception as e:
            self.memory.record_error("agent", str(e))
            return None

    # ═══════════════════════════════════════════════════════════════════
    # DECISION PARSING
    # ═══════════════════════════════════════════════════════════════════

    def _parse_decision(self, raw: str, ctx: Dict) -> Dict:
        parsed = self._extract_json(raw)

        if parsed is None:
            return self._wait("Réponse LLM non-parseable")

        decision = str(parsed.get("decision", "WAIT")).upper()
        if decision not in ("BUY", "SELL", "WAIT"):
            decision = "WAIT"

        thinking = str(parsed.get("thinking", ""))
        reasoning = str(parsed.get("reasoning", parsed.get("insight", "")))

        # Store thinking as episodic memory
        if thinking:
            self.memory.add_ai_insight(
                f"{self.last_analysis_instrument}: [{decision}] {thinking[:200]}"
            )

        return {
            "decision": decision,
            "confidence": min(1.0, max(0.0, float(parsed.get("confidence", 0.0)))),
            "stop_loss_pips": int(parsed.get("stop_loss_pips", 0) or 0),
            "take_profit_pips": int(parsed.get("take_profit_pips", 0) or 0),
            "reasoning": reasoning,
            "thinking": thinking,
            "risk_note": "agent_cot",
        }

    def _extract_json(self, text: str) -> Optional[Dict]:
        if not text:
            return None

        # Try direct parse
        try:
            return json.loads(text)
        except Exception:
            pass

        # Strip comments
        cleaned = self._strip_comments(text)

        # Find JSON block
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(cleaned[start:end + 1])
            except Exception:
                pass

            # Try to repair truncated JSON
            fragment = cleaned[start:]
            if fragment.count('"') % 2 == 1:
                fragment += '"'
            open_braces = fragment.count('{') - fragment.count('}')
            fragment += "}" * max(0, open_braces)
            try:
                return json.loads(fragment)
            except Exception:
                pass

        return None

    def _strip_comments(self, text: str) -> str:
        lines = []
        for line in text.split("\n"):
            result = line
            in_string = False
            for i in range(len(line) - 1):
                if line[i] == '"' and (i == 0 or line[i - 1] != '\\'):
                    in_string = not in_string
                if not in_string and line[i:i + 2] == '//':
                    result = line[:i]
                    break
            lines.append(result.rstrip())
        return "\n".join(lines)

    # ═══════════════════════════════════════════════════════════════════
    # VALIDATION
    # ═══════════════════════════════════════════════════════════════════

    def _validate(self, instrument: str, decision: Dict, ctx: Dict) -> Dict:
        if decision["decision"] == "WAIT":
            return decision

        # Confidence check
        if decision["confidence"] < self.min_confidence:
            self.memory.log_session(
                f"🛡️ {instrument}: confiance trop faible "
                f"({decision['confidence']:.0%} < {self.min_confidence:.0%})"
            )
            return self._wait(f"Confiance insuffisante ({decision['confidence']:.0%})")

        # Daily loss limit
        if ctx["today_pnl"] <= DAILY_LOSS_LIMIT:
            return self._wait(f"Limite perte journalière atteinte ({ctx['today_pnl']:.2f}$)")

        # Correlation block
        if ctx["strategies"]["correlation"]["blocked"]:
            reason = ctx["strategies"]["correlation"]["reason"]
            self.memory.log_session(f"🔗 {instrument}: bloqué corrélation — {reason}")
            return self._wait(f"Corrélation: {reason}")

        # Spread check
        spread = ctx["spread"]
        max_spread = self._max_spread(instrument)
        if spread > max_spread:
            return self._wait(f"Spread trop large ({spread:.1f} > {max_spread:.1f})")

        # Ensure SL/TP are set (use ATR as fallback)
        atr_pips = max(6, int(ctx["signal"].get("atr_pips", 15)))
        if decision["stop_loss_pips"] <= 0:
            decision["stop_loss_pips"] = atr_pips
        if decision["take_profit_pips"] <= 0:
            decision["take_profit_pips"] = max(decision["stop_loss_pips"], int(atr_pips * 2))

        # Risk multiplier from memory + protections + confluence
        risk_mult = (
            ctx["learning"]["risk_multiplier"]
            * ctx["protections"]["risk_adjustment"]
        )

        confluence_q = ctx["strategies"]["confluence"]["quality"]
        if confluence_q == "D":
            risk_mult *= 0.5
            self.memory.log_session(f"⚠️ {instrument}: confluence faible → risque ×0.5")
        elif confluence_q == "C":
            risk_mult *= 0.7

        if ctx["session"]["instrument_quality"] < 0.2:
            risk_mult *= 0.6
            self.memory.log_session(f"⚠️ {instrument}: session morte → risque ×0.6")

        htf_bias = ctx["strategies"]["htf_bias"]
        if htf_bias.get("combined_bias") == "conflict":
            risk_mult *= 0.5
            self.memory.log_session(f"⚠️ {instrument}: conflit HTF → risque ×0.5")

        decision["risk_multiplier"] = round(max(0.25, risk_mult), 2)

        return decision

    def _max_spread(self, instrument: str) -> float:
        name = str(instrument).upper()
        if name.startswith("XAU"):
            return 45.0
        if name.startswith(("BTC", "ETH")):
            return 120.0
        return 3.0

    def _wait(self, reason: str) -> Dict:
        return {
            "decision": "WAIT",
            "confidence": 0.0,
            "stop_loss_pips": 0,
            "take_profit_pips": 0,
            "reasoning": reason,
            "thinking": "",
            "risk_note": "agent_wait",
            "risk_multiplier": 1.0,
        }
