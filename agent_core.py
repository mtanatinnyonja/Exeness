"""
Agent IA de trading autonome — Architecture Multi-Agents.

3 agents spécialisés collaborent via pipeline séquentiel:
  1. Analyste    — lit le marché, identifie le setup
  2. Risk Manager — évalue les risques, valide ou bloque
  3. Décideur    — arbitre final, ne trade que sur consensus

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


PROMPT_ANALYSTE = """Tu es l'ANALYSTE technique. Lis la structure price action, identifie le régime et le setup.
JSON uniquement: {"setup":"description courte","direction":"BUY|SELL|NEUTRAL","force":1-5,"key_levels":"support/resistance","reasoning":"court"}"""

PROMPT_RISK = """Tu es le RISK MANAGER. Évalue les risques du setup proposé par l'Analyste.
Vérifie: spread vs ATR, session, protections, corrélation, news. Bloque si dangereux.
JSON uniquement: {"approved":true/false,"risk_score":1-10,"sl_pips":N,"tp_pips":N,"risk_notes":"raisons","reasoning":"court"}"""

PROMPT_DECIDEUR = """Tu es le DÉCIDEUR final. Tu vois l'analyse et l'évaluation des risques.
Trade UNIQUEMENT si: l'Analyste a un setup clair ET le Risk Manager approuve ET RR>=1.5.
En cas de doute ou désaccord → WAIT.
JSON uniquement: {"decision":"BUY|SELL|WAIT","confidence":0.0-1.0,"stop_loss_pips":N,"take_profit_pips":N,"reasoning":"court"}"""


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
        Analyse multi-agents: Analyste → Risk Manager → Décideur.
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

        # ═══ MULTI-AGENT PIPELINE ═══

        # Agent 1: ANALYSTE — identifie le setup
        analyste_prompt = self._build_analyste_prompt(instrument, ctx)
        self.last_prompt = analyste_prompt
        self.memory.log_session(f"📊 {instrument}: Agent Analyste en réflexion...")

        analyste_raw = self._call_ollama(analyste_prompt, instrument, PROMPT_ANALYSTE)
        if analyste_raw is None:
            self.memory.log_session(f"⏸️ {instrument}: LLM indisponible — WAIT")
            return self._wait("LLM indisponible — pas de trade sans analyse")

        analyste_json = self._extract_json(analyste_raw) or {}
        analyste_dir = str(analyste_json.get("direction", "NEUTRAL")).upper()
        analyste_force = int(analyste_json.get("force", 0) or 0)
        self.memory.log_session(
            f"📊 Analyste → {instrument}: {analyste_dir} force={analyste_force}/5 | "
            f"{analyste_json.get('reasoning', '')[:150]}"
        )

        # Si l'Analyste ne voit rien → stop
        if analyste_dir == "NEUTRAL" or analyste_force < 2:
            self.last_raw_response = analyste_raw
            self.last_parsed_response = {"analyste": analyste_json}
            return self._wait(f"Analyste: pas de setup clair ({analyste_dir} force={analyste_force})")

        # Agent 2: RISK MANAGER — évalue les risques
        risk_prompt = self._build_risk_prompt(instrument, ctx, analyste_json)
        self.memory.log_session(f"🛡️ {instrument}: Agent Risk Manager en réflexion...")

        risk_raw = self._call_ollama(risk_prompt, instrument, PROMPT_RISK)
        if risk_raw is None:
            self.last_raw_response = analyste_raw
            return self._wait("Risk Manager indisponible — WAIT par sécurité")

        risk_json = self._extract_json(risk_raw) or {}
        approved = risk_json.get("approved", False)
        risk_score = int(risk_json.get("risk_score", 10) or 10)
        self.memory.log_session(
            f"🛡️ Risk → {instrument}: {'✅ approuvé' if approved else '❌ bloqué'} "
            f"risque={risk_score}/10 | {risk_json.get('reasoning', '')[:150]}"
        )

        # Si le Risk Manager bloque → stop
        if not approved or risk_score >= 8:
            self.last_raw_response = f"ANALYSTE:\n{analyste_raw}\n\nRISK:\n{risk_raw}"
            self.last_parsed_response = {"analyste": analyste_json, "risk": risk_json}
            return self._wait(f"Risk Manager bloque (risque={risk_score}/10): {risk_json.get('risk_notes', '')[:100]}")

        # Agent 3: DÉCIDEUR — arbitre final
        decideur_prompt = self._build_decideur_prompt(instrument, ctx, analyste_json, risk_json)
        self.memory.log_session(f"⚖️ {instrument}: Agent Décideur en réflexion...")

        decideur_raw = self._call_ollama(decideur_prompt, instrument, PROMPT_DECIDEUR)
        if decideur_raw is None:
            self.last_raw_response = f"ANALYSTE:\n{analyste_raw}\n\nRISK:\n{risk_raw}"
            return self._wait("Décideur indisponible — WAIT par sécurité")

        self.last_raw_response = f"ANALYSTE:\n{analyste_raw}\n\nRISK:\n{risk_raw}\n\nDÉCIDEUR:\n{decideur_raw}"

        # Parse final decision
        decision = self._parse_decision(decideur_raw, ctx)
        decision["thinking"] = (
            f"Analyste: {analyste_json.get('setup', '')} → {analyste_dir} force={analyste_force} | "
            f"Risk: {'OK' if approved else 'BLOCK'} score={risk_score} | "
            f"Décideur: {decision.get('reasoning', '')[:200]}"
        )
        self.last_parsed_response = {
            "analyste": analyste_json,
            "risk": risk_json,
            "decideur": decision,
        }

        self.memory.log_session(
            f"⚖️ Décideur → {instrument}: {decision['decision']} "
            f"(conf: {decision.get('confidence', 0):.2f}) | {decision.get('reasoning', '')[:200]}"
        )

        # Store collective insight
        if decision["decision"] != "WAIT":
            insight = (
                f"{instrument}: Analyste={analyste_dir}(f{analyste_force}), "
                f"Risk={'OK' if approved else 'BLOCK'}({risk_score}), "
                f"Final={decision['decision']}({decision.get('confidence', 0):.0%})"
            )
            self.memory.add_ai_insight(insight)

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
    # MULTI-AGENT PROMPT BUILDERS
    # ═══════════════════════════════════════════════════════════════════

    def _compact_context(self, instrument: str, ctx: Dict) -> Dict:
        """Pre-compute shared compact data for all agents."""
        signal = ctx["signal"]
        details = signal.get("details", {})
        strategies = ctx["strategies"]

        confirm_text = ""
        if ctx["signal_confirm"]:
            sc = ctx["signal_confirm"]
            if sc["direction"] == signal["direction"] and sc["score"] >= 2:
                confirm_text = f"{CONFIRM_TIMEFRAME} confirme: {sc['direction']} {sc['score']}/5"
            else:
                confirm_text = f"{CONFIRM_TIMEFRAME} non aligné: {sc.get('direction', 'WAIT')} {sc['score']}/5"

        pa_text = ctx["price_action"]
        if len(pa_text) > 600:
            pa_text = pa_text[:600] + "..."

        strat_text = strategies['llm_context']
        if len(strat_text) > 400:
            strat_text = strat_text[:400] + "..."

        return {
            "header": (
                f"{instrument} Score:{signal['score']}/5 Dir:{signal.get('direction','WAIT')} "
                f"Regime:{details.get('market_regime','?')} "
                f"RSI:{details.get('rsi',50):.0f} Spread:{ctx['spread']:.1f}p ATR:{signal.get('atr_pips',0)}p "
                f"Supp:{details.get('support',0)} Res:{details.get('resistance',0)} "
                f"RR_buy:{details.get('rr_buy',0)} RR_sell:{details.get('rr_sell',0)}"
            ),
            "confirm": confirm_text,
            "pa": pa_text,
            "strat": strat_text,
            "prot": " | ".join(ctx["protections"]["warnings"][:3]) if ctx["protections"]["warnings"] else "OK",
            "news": ctx["news_ctx"] or "aucun",
            "account": f"Balance:{ctx['account'].get('balance',0):.0f}$ PnL:{ctx['today_pnl']:.2f}$ Pos:{len(ctx['open_positions'])}",
            "memory": f"Mem: {', '.join(ctx['learning']['reasons'])}" if ctx["learning"]["reasons"] else "",
        }

    def _build_analyste_prompt(self, instrument: str, ctx: Dict) -> str:
        c = self._compact_context(instrument, ctx)
        return f"""{c['header']}
{c['confirm']}

PRICE ACTION:
{c['pa']}

MTF/SMC:
{c['strat']}"""

    def _build_risk_prompt(self, instrument: str, ctx: Dict, analyste: Dict) -> str:
        c = self._compact_context(instrument, ctx)
        setup = analyste.get("setup", "?")
        direction = analyste.get("direction", "?")
        force = analyste.get("force", 0)
        return f"""{c['header']}
Analyste dit: {direction} force={force}/5 setup="{setup}"

Protections: {c['prot']}
News: {c['news']}
{c['account']} {c['memory']}"""

    def _build_decideur_prompt(self, instrument: str, ctx: Dict, analyste: Dict, risk: Dict) -> str:
        c = self._compact_context(instrument, ctx)
        return f"""{c['header']}

ANALYSTE: {analyste.get('direction','?')} force={analyste.get('force',0)} — {analyste.get('reasoning','')}
RISK: {'APPROUVÉ' if risk.get('approved') else 'BLOQUÉ'} risque={risk.get('risk_score','?')}/10 SL={risk.get('sl_pips',0)}p TP={risk.get('tp_pips',0)}p — {risk.get('reasoning','')}

{c['account']}"""

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

    def _call_ollama(self, prompt: str, instrument: str, system_prompt: str = "") -> Optional[str]:
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

            full_prompt = (system_prompt + "\n\n" + prompt) if system_prompt else prompt

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

        return {
            "decision": decision,
            "confidence": min(1.0, max(0.0, float(parsed.get("confidence", 0.0)))),
            "stop_loss_pips": int(parsed.get("stop_loss_pips", 0) or 0),
            "take_profit_pips": int(parsed.get("take_profit_pips", 0) or 0),
            "reasoning": reasoning,
            "thinking": thinking,
            "risk_note": "multi_agent",
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
