"""
Orchestrateur principal du robot local.
Flux: MT5 → signaux → mémoire → LLM local / règles → paper trade ou exécution MT5.
"""

import time
from datetime import datetime, timezone
from typing import Dict, List
from settings import (
    INSTRUMENTS, MIN_SIGNAL_SCORE, SIGNAL_COOLDOWN_MINUTES,
    MAX_OPEN_POSITIONS, MAX_RISK_PER_TRADE,
    MARKET_OPEN_HOUR, MARKET_CLOSE_HOUR, TRADE_DAYS,
    PRIMARY_TIMEFRAME, CONFIRM_TIMEFRAME, DAILY_LOSS_LIMIT, DAILY_TARGET,
)
from learning_store import AgentMemory
from mt5_bridge import build_broker
from signal_engine import calculate_signal_score
from local_llm import LocalIntelligence
from runtime_db import RuntimeStore


class TradeOrchestrator:
    def __init__(self, quiet: bool = False):
        self.memory = AgentMemory()
        self.store = RuntimeStore()
        self.broker = build_broker()
        self.intelligence = LocalIntelligence(self.memory)
        self.last_signal_time = {}

        if not quiet:
            self.memory.log_session(
                f"🚀 Robot démarré | broker={getattr(self.broker, 'name', 'unknown')} | ia={self.intelligence.provider}"
            )
            broker_note = getattr(self.broker, "status_message", "") or getattr(self.broker, "last_error", "")
            if broker_note:
                self.memory.log_session(f"🔌 {broker_note}")

    def is_market_open(self) -> bool:
        now = datetime.now(timezone.utc)
        return now.weekday() in TRADE_DAYS and MARKET_OPEN_HOUR <= now.hour < MARKET_CLOSE_HOUR

    def is_cooldown_active(self, instrument: str) -> bool:
        last_time = self.last_signal_time.get(instrument)
        if not last_time:
            return False
        elapsed = (datetime.utcnow() - last_time).total_seconds() / 60
        return elapsed < SIGNAL_COOLDOWN_MINUTES

    def get_target_instruments(self) -> List[str]:
        settings = self.store.get_settings()
        preferred = settings.get("preferred_symbols", INSTRUMENTS) or INSTRUMENTS
        mode = settings.get("symbol_source_mode", "preferred")

        if mode == "preferred":
            return list(preferred)

        try:
            if hasattr(self.broker, "get_active_symbols"):
                return self.broker.get_active_symbols(preferred)
        except Exception as e:
            self.memory.record_error("symbols", str(e))
        return list(preferred)

    def run_cycle(self):
        self.memory.log_session("═══ Cycle démarré ═══")

        if not self.is_market_open():
            self.memory.log_session("⏸️ Marché fermé - cycle ignoré")
            return

        try:
            account = self.broker.get_account_summary()
            open_positions = self.broker.get_open_positions()
            self.memory.log_session(
                f"💰 Balance: ${account.get('balance', 0):.2f} | "
                f"P&L: ${account.get('unrealized_pnl', 0):.2f} | "
                f"Positions: {len(open_positions)}"
            )
        except Exception as e:
            self.memory.record_error("broker", str(e))
            self.memory.log_session(f"❌ Erreur broker: {e}")
            return

        settings = self.store.get_settings()
        max_open_positions = int(settings.get("max_open_positions", MAX_OPEN_POSITIONS))
        daily_loss_limit = float(settings.get("daily_loss_limit", DAILY_LOSS_LIMIT))
        daily_target = float(settings.get("daily_target", DAILY_TARGET))

        if len(open_positions) >= max_open_positions:
            self.memory.log_session(f"⚠️ Max positions atteint ({max_open_positions})")
            self._check_existing_positions(open_positions)
            return

        today_pnl = self.memory.get_daily_pnl()
        if daily_loss_limit < 0 and today_pnl <= daily_loss_limit:
            self.memory.log_session(f"🛑 Perte journalière limite atteinte: ${today_pnl:.2f}")
            return
        if daily_target > 0 and today_pnl >= daily_target:
            self.memory.log_session(f"🎯 Objectif journalier atteint: ${today_pnl:.2f}")
            return

        instruments = self.get_target_instruments()
        if not instruments:
            self.memory.log_session("⚠️ Aucun symbole visible dans MT5 - rien à analyser")
            return

        self.memory.log_session(f"📡 Symboles actifs: {', '.join(instruments)}")

        for instrument in instruments:
            self._analyze_instrument(instrument, account)
            time.sleep(0.2)

        self.memory.log_session("═══ Cycle terminé ═══")

    def _analyze_instrument(self, instrument: str, account: Dict):
        if self.is_cooldown_active(instrument):
            self.memory.log_session(f"⏳ {instrument}: cooldown actif")
            return

        try:
            candles_h1 = self.broker.get_candles(instrument, PRIMARY_TIMEFRAME, 120)
            candles_m15 = self.broker.get_candles(instrument, CONFIRM_TIMEFRAME, 80)
            if len(candles_h1) < 60 or len(candles_m15) < 30:
                self.memory.log_session(f"⚠️ {instrument}: données insuffisantes")
                return

            signal_h1 = calculate_signal_score(candles_h1)
            signal_m15 = calculate_signal_score(candles_m15)
            score = signal_h1["score"]
            direction = signal_h1["direction"]

            if signal_h1["direction"] == signal_m15["direction"] and signal_m15["score"] >= 2:
                score += 1
                self.memory.log_session(f"✅ {instrument}: alignement TF ({score}/6)")
            else:
                self.memory.log_session(f"📊 {instrument}: score H1={score}/5 | direction={direction}")

            learning = self.memory.assess_setup(instrument, signal_h1)
            if learning["reasons"]:
                self.memory.log_session(f"🧠 {instrument}: mémoire → {', '.join(learning['reasons'])}")
            if learning["blocked"]:
                self.memory.log_session(f"🛡️ {instrument}: setup bloqué par la mémoire locale")
                return

            spread = self.broker.get_spread_pips(instrument)
            if spread > 4.0:
                self.memory.log_session(f"⚠️ {instrument}: spread trop large ({spread:.1f} pips)")
                return

            self.last_signal_time[instrument] = datetime.utcnow()
            market_ctx = (
                f"Spread actuel: {spread:.1f} pips. Heure UTC: {datetime.utcnow().hour}h. "
                f"Broker: {getattr(self.broker, 'name', 'unknown')}. "
                f"Score technique brut: {score}/5. Direction brute: {direction or 'WAIT'}"
            )

            decision = self.intelligence.analyze_signal(instrument, signal_h1, account, market_ctx)
            if score < MIN_SIGNAL_SCORE or direction is None:
                self.memory.log_session(f"🧪 {instrument}: signal faible envoyé au LLM pour validation finale")
            if not decision:
                return

            self.store.record_signal_sample(instrument, signal_h1, spread, decision)

            decision["risk_multiplier"] = learning["risk_multiplier"]
            if decision["decision"] in ["BUY", "SELL"]:
                self._execute_trade(instrument, decision, signal_h1, account)
            else:
                self.memory.log_session(f"⏸️ {instrument}: IA dit WAIT - {decision.get('reasoning', '')[:90]}")

        except Exception as e:
            self.memory.record_error(f"analysis:{instrument}", str(e))
            self.memory.log_session(f"❌ Erreur analyse {instrument}: {e}")

    def _execute_trade(self, instrument: str, decision: Dict, signal: Dict, account: Dict):
        direction = decision["decision"]
        sl_pips = max(1, int(decision.get("stop_loss_pips", 20) or signal.get("atr_pips", 20) or 20))
        tp_pips = max(sl_pips, int(decision.get("take_profit_pips", sl_pips * 2) or sl_pips * 2))
        confidence = float(decision.get("confidence", 0.5))
        risk_multiplier = float(decision.get("risk_multiplier", 1.0))

        settings = self.store.get_settings()
        max_risk = float(settings.get("max_risk_per_trade", MAX_RISK_PER_TRADE))
        risk_usd = max(0.5, account.get("balance", 0) * max_risk * risk_multiplier)
        units = self.broker.calculate_units(instrument, risk_usd, sl_pips)

        self.memory.log_session(
            f"📈 Ordre: {direction} {instrument} | units={units} | SL={sl_pips}p | TP={tp_pips}p | risque=${risk_usd:.2f}"
        )

        order = self.broker.place_market_order(
            instrument=instrument,
            direction=direction,
            units=units,
            stop_loss_pips=sl_pips,
            take_profit_pips=tp_pips,
            comment=f"LOCAL|{signal.get('pattern', '')[:20]}|{int(confidence * 100)}"
        )

        if order:
            trade_id = self.memory.add_trade({
                "instrument": instrument,
                "direction": direction,
                "units": units,
                "entry_price": order.get("entry_price", 0.0),
                "stop_loss": order.get("stop_loss", 0.0),
                "take_profit": order.get("take_profit", 0.0),
                "broker_id": order.get("broker_id"),
                "pattern": signal.get("pattern"),
                "signal_score": signal.get("score", 0),
                "confidence": confidence,
                "sl_pips": sl_pips,
                "tp_pips": tp_pips,
                "risk_usd": risk_usd,
                "reasoning": decision.get("reasoning", ""),
                "status": order.get("status", "open")
            })
            self.memory.log_session(
                f"✅ Trade #{trade_id} créé: {direction} {instrument} @ {order.get('entry_price', 0):.5f} [{order.get('status', 'open')}]"
            )
        else:
            self.memory.log_session(f"❌ Échec ordre {instrument}")

    def _check_existing_positions(self, positions: List[Dict]):
        for pos in positions:
            upnl = float(pos.get("unrealized_pnl", 0))
            emoji = "📈" if upnl >= 0 else "📉"
            self.memory.log_session(
                f"{emoji} Position {pos.get('instrument')} {pos.get('direction')}: P&L non réalisé = ${upnl:.2f}"
            )

    def preview_ai_decision(self, instrument: str = None) -> Dict:
        symbols = self.get_target_instruments()
        target = instrument or (symbols[0] if symbols else None)
        if not target:
            return {
                "instrument": None,
                "signal": {},
                "decision": {
                    "decision": "WAIT",
                    "confidence": 0.0,
                    "reasoning": "Aucun symbole visible dans MT5 pour lancer le test IA."
                },
                "provider": self.intelligence.provider,
                "spread": 0.0,
            }

        account = self.broker.get_account_summary()
        candles = self.broker.get_candles(target, PRIMARY_TIMEFRAME, 120)
        signal = calculate_signal_score(candles)

        if not signal.get("direction"):
            signal["direction"] = "BUY"
        if signal.get("score", 0) < MIN_SIGNAL_SCORE:
            signal["score"] = MIN_SIGNAL_SCORE + 1
            signal["pattern"] = signal.get("pattern") or "forced_test_mode"

        spread = self.broker.get_spread_pips(target)
        context = f"Mode test dashboard. Spread actuel: {spread:.1f} pips."
        decision = self.intelligence.analyze_signal(target, signal, account, context)
        self.store.record_signal_sample(target, signal, spread, decision or {"decision": "WAIT", "confidence": 0})
        return {
            "instrument": target,
            "signal": signal,
            "decision": decision,
            "provider": self.intelligence.provider,
            "spread": spread,
        }

    def get_status(self) -> Dict:
        try:
            account = self.broker.get_account_summary()
            positions = self.broker.get_open_positions()
        except Exception as e:
            self.memory.record_error("status", str(e))
            account = {"balance": 0, "unrealized_pnl": 0, "nav": 0, "open_trades": 0, "connected": False}
            positions = []

        runtime_settings = self.store.get_settings()
        ml_stats = self.store.get_ml_stats()
        llm_calls = self.memory.get_llm_calls_today()
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "market_open": self.is_market_open(),
            "active_symbols": self.get_target_instruments(),
            "account": account,
            "open_positions": positions,
            "daily_pnl": self.memory.get_daily_pnl(),
            "total_pnl": self.memory.memory.get("total_pnl", 0),
            "win_rate": self.memory.get_win_rate(),
            "total_trades": self.memory.memory.get("total_trades", 0),
            "llm_calls_today": llm_calls,
            "api_calls_today": llm_calls,
            "recent_trades": self.memory.get_recent_trades(5),
            "session_log": self.memory.memory.get("session_log", [])[-20:],
            "best_patterns": self.memory.get_best_patterns()[:3],
            "broker": {
                "name": getattr(self.broker, "name", "unknown"),
                "connected": getattr(self.broker, "connected", False),
                "safe_to_trade": getattr(self.broker, "safe_to_trade", False),
                "status_message": getattr(self.broker, "status_message", ""),
            },
            "settings": runtime_settings,
            "ai_provider": self.intelligence.provider,
            "token_usage": self.memory.get_token_usage_today(),
            "ml_stats": ml_stats,
            "learned_filters": self.memory.memory.get("learned_filters", [])[-5:],
            "runtime_mode": "local-only",
            "profit_target_enabled": float(runtime_settings.get("daily_target", DAILY_TARGET)) > 0,
        }


TradingAgent = TradeOrchestrator
