"""
Agent IA de trading autonome — Architecture Multi-Agents.

3 agents spécialisés collaborent via pipeline séquentiel:
  1. Analyste    — lit le marché, identifie le setup
  2. Risk Manager — évalue les risques, valide ou bloque
  3. Décideur    — arbitre final, ne trade que sur consensus

Si le LLM est indisponible après retry, fallback technique activable via
LLM_FALLBACK_TECHNICAL dans settings.py.
"""

import json
import re
import time
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
    DAILY_LOSS_LIMIT, LLM_FALLBACK_TECHNICAL,
    LLM_ENABLED, LLM_AS_FINAL_VALIDATOR,
    ENABLE_SIGNAL_QUALITY_FILTER, SIGNAL_QUALITY_MIN_SCORE,
    SIGNAL_QUALITY_MIN_BIAS, ENABLE_MARKET_CONTEXT,
    MAX_TRADES_PER_DAY, TRADE_COOLDOWN_MINUTES,
    ENABLE_HUMAN_LIKE_MODE, HUMAN_LIKE_MIN_SCORE,
    HUMAN_LIKE_MIN_BIAS, HUMAN_LIKE_MAX_RECENT_TRADES,
    HUMAN_LIKE_TARGET_TRADES_PER_DAY, HUMAN_LIKE_MIN_TRADES_PER_DAY,
    ENABLE_AGENT_COMMUNICATION_MODE,
)
from signal_engine import (
    calculate_signal_score, build_price_action_description, _MIN_CANDLES,
)
from market_protection import run_all_protections
from market_context import analyze_market_context
from signal_filter import filter_signal_quality
from trade_planner import plan_trade_idea
from agent_communication import (
    build_analyst_prompt as build_analyst_conversation_prompt,
    build_risk_prompt as build_risk_conversation_prompt,
    build_decider_prompt as build_decider_conversation_prompt,
    build_reviewer_prompt,
)
from smart_strategies import (
    get_session_score, calculate_htf_bias, get_smart_money_context,
    build_strategies_context, check_correlation_risk,
)
from economic_calendar import EconomicCalendar
from runtime_db import RuntimeStore
from audit_logger import get_audit_logger


PROMPT_ANALYSTE = """Tu es l'ANALYSTE technique. Lis la structure price action, identifie le régime et le setup.
JSON uniquement: {"setup":"description courte","direction":"BUY|SELL|NEUTRAL","force":1-5,"key_levels":"support/resistance","reasoning":"court"}"""

PROMPT_RISK = """Tu es le RISK MANAGER. Évalue les risques du setup proposé par l'Analyste.
Vérifie: spread vs ATR, session, protections, corrélation, news. Bloque si dangereux.
JSON uniquement: {"approved":true/false,"risk_score":1-10,"sl_pips":N,"tp_pips":N,"risk_notes":"raisons","reasoning":"court"}"""

PROMPT_DECIDEUR = """Tu es le DÉCIDEUR final. Tu vois l'analyse et l'évaluation des risques.
Trade UNIQUEMENT si: l'Analyste a un setup clair ET le Risk Manager approuve ET RR>=1.5.
En cas de doute ou désaccord → WAIT.
JSON uniquement: {"decision":"BUY|SELL|WAIT","confidence":0.0-1.0,"stop_loss_pips":N,"take_profit_pips":N,"reasoning":"court"}"""

PROMPT_GARDIEN = """Tu es le GARDIEN de positions. Tu surveilles un trade ouvert et décides:
- HOLD: garder la position, tout va bien
- CLOSE: couper maintenant (retournement, danger, objectif atteint)
- TIGHTEN: resserrer le SL pour sécuriser les gains
Analyse le P&L, la structure actuelle, et les signaux de retournement.
JSON uniquement: {"action":"HOLD|CLOSE|TIGHTEN","urgency":1-10,"new_sl_pips":N,"reasoning":"court"}"""


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
        self.audit = get_audit_logger()

        # State for dashboard / debug
        self.last_prompt = ""
        self.last_raw_response = ""
        self.last_parsed_response = None
        self.last_analysis_instrument = ""
        self.last_analysis_timestamp = ""
        self._llm_healthy = True   # état LLM visible par le dashboard

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
        self.llm_enabled = bool(settings.get("enable_llm", LLM_ENABLED))
        self.llm_final_validator = bool(settings.get("llm_as_final_validator", LLM_AS_FINAL_VALIDATOR))
        self.signal_filter_enabled = bool(settings.get("enable_signal_quality_filter", ENABLE_SIGNAL_QUALITY_FILTER))
        self.signal_quality_min_score = int(settings.get("signal_quality_min_score", SIGNAL_QUALITY_MIN_SCORE))
        self.signal_quality_min_bias = float(settings.get("signal_quality_min_bias", SIGNAL_QUALITY_MIN_BIAS))
        self.market_context_enabled = bool(settings.get("enable_market_context", ENABLE_MARKET_CONTEXT))
        self.max_trades_per_day = int(settings.get("max_trades_per_day", MAX_TRADES_PER_DAY))
        self.trade_cooldown_minutes = int(settings.get("trade_cooldown_minutes", TRADE_COOLDOWN_MINUTES))
        self.human_like_mode = bool(settings.get("enable_human_like_mode", ENABLE_HUMAN_LIKE_MODE))
        self.human_like_min_score = int(settings.get("human_like_min_score", HUMAN_LIKE_MIN_SCORE))
        self.human_like_min_bias = float(settings.get("human_like_min_bias", HUMAN_LIKE_MIN_BIAS))
        self.human_like_max_recent_trades = int(settings.get("human_like_max_recent_trades", HUMAN_LIKE_MAX_RECENT_TRADES))
        self.human_like_target_trades_per_day = int(settings.get("human_like_target_trades_per_day", HUMAN_LIKE_TARGET_TRADES_PER_DAY))
        self.human_like_min_trades_per_day = int(settings.get("human_like_min_trades_per_day", HUMAN_LIKE_MIN_TRADES_PER_DAY))
        self.agent_communication_enabled = bool(settings.get("enable_agent_communication_mode", ENABLE_AGENT_COMMUNICATION_MODE))

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

        if self.market_context_enabled:
            ctx["market_context"] = analyze_market_context(ctx["candles_h1"], instrument)
        else:
            ctx["market_context"] = {"category": "unknown", "reason": "désactivé"}

        ctx["trades_today"] = self.memory.get_trades_started_today()
        ctx["recent_trades"] = self.memory.get_recent_trade_count(self.trade_cooldown_minutes)

        ctx["trade_plan"] = plan_trade_idea(
            ctx,
            open_positions,
            {
                "human_like_min_score": self.human_like_min_score,
                "human_like_min_bias": self.human_like_min_bias,
                "max_open_positions": int(self.store.get_settings().get("max_open_positions", 3)),
                "max_trades_per_day": self.max_trades_per_day,
                "trades_today": ctx["trades_today"],
                "recent_trades": ctx["recent_trades"],
                "max_recent_trades": self.human_like_max_recent_trades,
                "target_trades_per_day": self.human_like_target_trades_per_day,
                "min_trades_per_day": self.human_like_min_trades_per_day,
            },
        )

        plan = ctx["trade_plan"]
        self.memory.log_session(
            f"🧭 {instrument}: Planner → {plan['direction']} conf={plan['confidence']:.2f} "
            f"bloqué={plan['is_blocking']} notes={';'.join(plan.get('notes', []))}"
        )
        if self.human_like_mode and plan["is_blocking"]:
            return self._wait(f"Planner: {plan['reasoning']}")

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
        self.memory.log_session(
            f"🌍 {instrument}: contexte marché={ctx['market_context']['category']} "
            f"({ctx['market_context']['reason']})"
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

        if self.signal_filter_enabled:
            filter_result = filter_signal_quality(
                ctx["signal"],
                ctx.get("signal_confirm"),
                ctx["market_context"],
                len(open_positions),
                self.memory,
                {
                    "min_signal_score": self.signal_quality_min_score,
                    "min_signal_bias": self.signal_quality_min_bias,
                    "max_open_positions": int(self.store.get_settings().get("max_open_positions", 3)),
                    "max_trades_per_day": self.max_trades_per_day,
                    "trade_cooldown_minutes": self.trade_cooldown_minutes,
                },
            )
            if filter_result["blocked"]:
                self.memory.log_session(
                    f"🚫 {instrument}: signal bloqué par filtre qualité — {filter_result['reason']}"
                )
                return self._wait(f"Filtre qualité signal: {filter_result['reason']}")

        # ═══ MULTI-AGENT PIPELINE ═══

        # Agent 1: ANALYSTE — identifie le setup
        if self.agent_communication_enabled:
            analyste_prompt = build_analyst_conversation_prompt(instrument, ctx)
        else:
            analyste_prompt = self._build_analyste_prompt(instrument, ctx)
        self.last_prompt = analyste_prompt
        self.memory.log_session(f"📊 {instrument}: Agent Analyste en réflexion...")

        analyste_raw = self._call_ollama(analyste_prompt, instrument, PROMPT_ANALYSTE)
        if analyste_raw is None:
            # LLM indisponible → fallback technique si activé
            if LLM_FALLBACK_TECHNICAL:
                return self._technical_fallback_decision(instrument, ctx)
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
            self._persist_last_exchange()
            return self._wait(f"Analyste: pas de setup clair ({analyste_dir} force={analyste_force})")

        # Agent 2: RISK MANAGER — évalue les risques
        if self.agent_communication_enabled:
            risk_prompt = build_risk_conversation_prompt(instrument, ctx, analyste_json)
        else:
            risk_prompt = self._build_risk_prompt(instrument, ctx, analyste_json)
        self.memory.log_session(f"🛡️ {instrument}: Agent Risk Manager en réflexion...")

        risk_raw = self._call_ollama(risk_prompt, instrument, PROMPT_RISK)
        if risk_raw is None:
            self.last_raw_response = analyste_raw
            self.last_parsed_response = {"analyste": analyste_json}
            self._persist_last_exchange()
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
            self._persist_last_exchange()
            return self._wait(f"Risk Manager bloque (risque={risk_score}/10): {risk_json.get('risk_notes', '')[:100]}")

        # Agent 3: DÉCIDEUR — arbitre final
        if self.agent_communication_enabled:
            decideur_prompt = build_decider_conversation_prompt(instrument, ctx, analyste_json, risk_json)
        else:
            decideur_prompt = self._build_decideur_prompt(instrument, ctx, analyste_json, risk_json)
        self.memory.log_session(f"⚖️ {instrument}: Agent Décideur en réflexion...")

        decideur_raw = self._call_ollama(decideur_prompt, instrument, PROMPT_DECIDEUR)
        if decideur_raw is None:
            self.last_raw_response = f"ANALYSTE:\n{analyste_raw}\n\nRISK:\n{risk_raw}"
            self.last_parsed_response = {"analyste": analyste_json, "risk": risk_json}
            self._persist_last_exchange()
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
        self._persist_last_exchange()

        if self.agent_communication_enabled:
            reviewer_prompt = build_reviewer_prompt(instrument, ctx, analyste_json, risk_json, decision)
            reviewer_raw = self._call_ollama(reviewer_prompt, instrument, PROMPT_DECIDEUR)
            if reviewer_raw:
                reviewer_json = self._extract_json(reviewer_raw) or {}
                if reviewer_json.get("allow") is False:
                    reason = reviewer_json.get("reasoning", "relecteur bloque")
                    self.memory.log_session(f"📝 Relecteur → {instrument}: bloque | {reason}")
                    self.last_raw_response += f"\n\nRELECTEUR:\n{reviewer_raw}"
                    self.last_parsed_response["reviewer"] = reviewer_json
                    return self._wait(f"Relecteur bloque: {reason}")
                self.last_parsed_response["reviewer"] = reviewer_json
                self.memory.log_session(
                    f"📝 Relecteur → {instrument}: allow={reviewer_json.get('allow')} "
                    f"reason={reviewer_json.get('reasoning', '')[:120]}"
                )

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
        if self.last_prompt or self.last_raw_response or self.last_parsed_response:
            return {
                "instrument": self.last_analysis_instrument,
                "timestamp": self.last_analysis_timestamp,
                "prompt": self.last_prompt,
                "raw_response": self.last_raw_response,
                "parsed_response": self.last_parsed_response,
                "provider": self.provider,
                "model": self.model,
                "llm_healthy": self._llm_healthy,
            }
        return self.memory.get_last_ai_exchange() or {
            "instrument": self.last_analysis_instrument,
            "timestamp": self.last_analysis_timestamp,
            "prompt": self.last_prompt,
            "raw_response": self.last_raw_response,
            "parsed_response": self.last_parsed_response,
            "provider": self.provider,
            "model": self.model,
            "llm_healthy": self._llm_healthy,
        }

    def _persist_last_exchange(self):
        try:
            self.memory.update_last_ai_exchange(self.get_last_exchange())
        except Exception:
            pass

    def monitor_position(self, position: Dict, account: Dict) -> Dict:
        """
        Agent Gardien: surveille une position ouverte et décide HOLD/CLOSE/TIGHTEN.
        Appelé à chaque cycle pour chaque position existante.
        """
        self._load_settings()
        instrument = position.get("instrument", "")
        direction = str(position.get("direction", "")).upper()
        entry = float(position.get("entry_price") or position.get("open_price") or 0)
        current = float(position.get("current_price") or 0)
        upnl = float(position.get("unrealized_pnl", 0))
        sl = float(position.get("stop_loss") or 0)
        tp = float(position.get("take_profit") or 0)

        if not instrument or not direction or not entry:
            return {"action": "HOLD", "reasoning": "données position insuffisantes"}

        # Gather fresh market data
        try:
            candles = self.broker.get_candles(instrument, PRIMARY_TIMEFRAME, 60)
            if len(candles) < 20:
                return {"action": "HOLD", "reasoning": "données marché insuffisantes"}
        except Exception:
            return {"action": "HOLD", "reasoning": "erreur données marché"}

        signal = calculate_signal_score(candles, instrument)
        details = signal.get("details", {})
        spread = self.broker.get_spread_pips(instrument)

        # Quick check: if signal strongly opposes position → ask LLM
        signal_dir = signal.get("direction", "WAIT")
        signal_score = signal.get("score", 0)

        # Build Gardien prompt
        prompt = self._build_gardien_prompt(
            instrument, direction, entry, current, upnl, sl, tp,
            spread, signal, details, account
        )

        self.memory.log_session(f"👁️ {instrument}: Agent Gardien surveille {direction} P&L=${upnl:.2f}...")

        raw = self._call_ollama(prompt, instrument, PROMPT_GARDIEN)
        if raw is None:
            # LLM indisponible → fallback mécanique sûr
            if upnl < -3.0:
                self.memory.log_session(f"⚠️ {instrument}: Gardien offline, perte ${upnl:.2f} → CLOSE par sécurité")
                return {"action": "CLOSE", "reasoning": f"LLM offline + perte ${upnl:.2f}", "urgency": 8}
            return {"action": "HOLD", "reasoning": "Gardien offline, position stable"}

        parsed = self._extract_json(raw) or {}
        action = str(parsed.get("action", "HOLD")).upper()
        if action not in ("HOLD", "CLOSE", "TIGHTEN"):
            action = "HOLD"

        urgency = min(10, max(1, int(parsed.get("urgency", 1) or 1)))
        reasoning = str(parsed.get("reasoning", ""))
        new_sl_pips = int(parsed.get("new_sl_pips", 0) or 0)

        emoji = {"HOLD": "✅", "CLOSE": "🔴", "TIGHTEN": "🔄"}.get(action, "❓")
        self.memory.log_session(
            f"{emoji} Gardien → {instrument} {direction}: {action} (urgence={urgency}/10) | {reasoning[:150]}"
        )

        return {
            "action": action,
            "urgency": urgency,
            "new_sl_pips": new_sl_pips,
            "reasoning": reasoning,
        }

    def _build_gardien_prompt(self, instrument, direction, entry, current, upnl,
                               sl, tp, spread, signal, details, account):
        signal_dir = signal.get("direction", "WAIT")
        regime = details.get("market_regime", "?")
        rsi = details.get("rsi", 50)
        score = signal.get("score", 0)
        atr = signal.get("atr_pips", 0)

        # Reversal alert
        reversal = ""
        if direction == "BUY" and signal_dir == "SELL" and score >= 3:
            reversal = "⚠️ SIGNAL CONTRAIRE: marché dit SELL force {}/5".format(score)
        elif direction == "SELL" and signal_dir == "BUY" and score >= 3:
            reversal = "⚠️ SIGNAL CONTRAIRE: marché dit BUY force {}/5".format(score)

        return f"""POSITION OUVERTE: {instrument} {direction}
Entry:{entry} Current:{current} P&L:${upnl:.2f}
SL:{sl} TP:{tp} Spread:{spread:.1f}p

MARCHÉ ACTUEL:
Signal:{signal_dir} Score:{score}/5 Regime:{regime} RSI:{rsi:.0f} ATR:{atr}p
{reversal}

Balance:{account.get('balance',0):.0f}$ Positions:{account.get('open_trades',0)}"""

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

        market_context = ctx.get("market_context", {})
        plan_text = ""
        if ctx.get("trade_plan"):
            plan = ctx["trade_plan"]
            plan_text = (
                f"Plan:{plan.get('direction','WAIT')} conf={plan.get('confidence',0):.2f} "
                f"bloqué={plan.get('is_blocking')} notes={';'.join(plan.get('notes', []))}"
            )

        return {
            "header": (
                f"{instrument} Score:{signal['score']}/5 Dir:{signal.get('direction','WAIT')} "
                f"Regime:{details.get('market_regime','?')} "
                f"Market:{market_context.get('category','?')} "
                f"RSI:{details.get('rsi',50):.0f} Spread:{ctx['spread']:.1f}p ATR:{signal.get('atr_pips',0)}p "
                f"Supp:{details.get('support',0)} Res:{details.get('resistance',0)} "
                f"RR_buy:{details.get('rr_buy',0)} RR_sell:{details.get('rr_sell',0)}"
            ),
            "plan": plan_text,
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
        plan_section = f"PLAN: {c['plan']}\n\n" if c.get('plan') else ""
        return f"""{c['header']}\n{plan_section}
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

    def _build_final_validator_prompt(self, instrument: str, ctx: Dict, decision: Dict) -> str:
        c = self._compact_context(instrument, ctx)
        return f"""Valide la décision finale pour {instrument}.

CONTEXTE MARCHÉ:
{c['header']}
Contexte marché: {ctx['market_context']['category']} — {ctx['market_context']['reason']}

DÉCISION CANDIDATE:
Décision: {decision['decision']}
Confiance: {decision['confidence']:.2f}
SL: {decision['stop_loss_pips']}p TP: {decision['take_profit_pips']}p
Reasoning: {decision.get('reasoning','')}

Réponds uniquement en JSON: {{"allow":true/false,"reasoning":"court"}}"""

    def _llm_final_validation(self, instrument: str, decision: Dict, ctx: Dict) -> Optional[Dict]:
        prompt = self._build_final_validator_prompt(instrument, ctx, decision)
        raw = self._call_ollama(prompt, instrument, PROMPT_DECIDEUR)
        if raw is None:
            self.memory.log_session(f"🧠 {instrument}: validateur LLM final indisponible")
            return None
        parsed = self._extract_json(raw) or {}
        if "allow" not in parsed:
            return None
        return {
            "allow": bool(parsed.get("allow", False)),
            "reasoning": str(parsed.get("reasoning", "")),
        }

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
        """Appel LLM local avec 1 retry automatique après 5s si échec."""
        if not self.llm_enabled:
            self.memory.log_session(f"🔒 {instrument}: LLM désactivé par configuration")
            self._llm_healthy = False
            return None
        if requests is None:
            self.memory.record_error("agent", "package requests absent")
            self._llm_healthy = False
            return None
        if ONLY_ALLOW_LOCAL_LLM and not self._is_local_endpoint(self.endpoint):
            self.memory.record_error("agent", f"endpoint non-local refusé: {self.endpoint}")
            self._llm_healthy = False
            return None

        tokens = self._approx_tokens(prompt)
        if not self._can_call(tokens):
            self.memory.record_error("agent", "budget LLM épuisé")
            return None

        full_prompt = (system_prompt + "\n\n" + prompt) if system_prompt else prompt
        payload = {
            "model": self.model,
            "prompt": full_prompt,
            "stream": False,
            "options": {
                "temperature": self.temperature,
                "num_predict": 200,
            },
            "keep_alive": "10m",
        }

        last_error = None
        for attempt in range(2):          # 1 essai + 1 retry
            if attempt > 0:
                self.memory.log_session(f"⟳ {instrument}: retry LLM dans 5s (tentative {attempt+1}/2)...")
                time.sleep(5)
            try:
                self.memory.increment_llm_calls()
                self.memory.record_token_usage(prompt_tokens=tokens, completion_tokens=0)

                response = requests.post(
                    self.endpoint,
                    headers={"Content-Type": "application/json"},
                    json=payload,
                    timeout=self.timeout,
                )
                response.raise_for_status()
                data = response.json()
                raw = (data.get("response") or "").strip()

                completion_tokens = self._approx_tokens(raw)
                self.memory.record_token_usage(prompt_tokens=0, completion_tokens=completion_tokens)

                if not raw:
                    self.memory.record_error("agent", "réponse vide du LLM")
                    last_error = "réponse vide"
                    continue

                self._llm_healthy = True
                return raw

            except Exception as e:
                last_error = str(e)
                self.memory.record_error("agent", f"tentative {attempt+1}/2: {e}")

        # Les 2 tentatives ont échoué
        self._llm_healthy = False
        self.memory.log_session(f"🔴 LLM indisponible après 2 tentatives: {last_error}")
        return None

    def _technical_fallback_decision(self, instrument: str, ctx: Dict) -> Dict:
        """
        Fallback purement technique quand le LLM est indisponible.
        Utilise le signal_score + direction calculés par signal_engine.
        Politique conservatrice : seuil élevé (score >= 4), risque réduit.
        """
        self.memory.log_session(
            f"⚙️ {instrument}: LLM offline — fallback technique activé"
        )

        signal = ctx.get("signal", {})
        score = int(signal.get("score", 0))
        direction = str(signal.get("direction", "WAIT")).upper()
        protections = ctx.get("protections", {})
        blocked = protections.get("blocked", False)

        # Bloque si une protection est active
        if blocked:
            return self._wait("Fallback technique: protection active, WAIT")

        # Exige un score >= 4 (vs 2 en mode normal) — conservateur
        if direction in ("BUY", "SELL") and score >= 4:
            atr_pips = int(signal.get("atr_pips", 20))
            sl_pips = max(10, min(atr_pips, 50))   # bornes de sécurité
            tp_pips = int(sl_pips * 1.5)            # RR minimum 1.5

            self.memory.log_session(
                f"⚙️ {instrument}: Fallback → {direction} score={score}/5 "
                f"SL={sl_pips}p TP={tp_pips}p (LLM absent)"
            )
            return {
                "decision": direction,
                "confidence": 0.40,             # valeur sentinelle < LLM_MIN_CONFIDENCE (0.60)
                "stop_loss_pips": sl_pips,
                "take_profit_pips": tp_pips,
                "reasoning": f"Fallback technique (LLM offline): score={score}, dir={direction}",
                "thinking": "LLM indisponible — décision technique pure",
                "risk_note": "technical_fallback",
                "risk_multiplier": 0.5,         # risque réduit de moitié en fallback
            }

        return self._wait(f"Fallback technique: score={score} direction={direction} insuffisant")

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

        if self.llm_final_validator and self.llm_enabled:
            validator = self._llm_final_validation(instrument, decision, ctx)
            if validator is not None and not validator.get("allow", True):
                self.memory.log_session(
                    f"🧠 {instrument}: LLM final valideur bloque → {validator.get('reasoning','aucune raison')}"
                )
                return self._wait(f"LLM final bloque: {validator.get('reasoning','aucune raison')}")

        # Confidence check — le fallback technique a confidence=0.40,
        # ce qui est < min_confidence (0.60) donc il sera bloqué ici
        # sauf si on le laisse passer explicitement via risk_note
        if decision.get("risk_note") != "technical_fallback":
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
        risk_mult = decision.get("risk_multiplier", 1.0) * (
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