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
from signal_engine import calculate_signal_score, _MIN_CANDLES
from local_llm import LocalIntelligence
from runtime_db import RuntimeStore
from ml_model import LocalSignalModel


class TradeOrchestrator:
    def __init__(self, quiet: bool = False):
        self.memory = AgentMemory()
        self.store = RuntimeStore()
        self.broker = build_broker()
        self.intelligence = LocalIntelligence(self.memory)
        self.ml_model = LocalSignalModel(self.store, self.broker)
        self.last_signal_time = {}

        if not quiet:
            self.memory.log_session(
                f"🚀 Robot démarré | broker={getattr(self.broker, 'name', 'unknown')} | ia={self.intelligence.provider}"
            )
            broker_note = getattr(self.broker, "status_message", "") or getattr(self.broker, "last_error", "")
            if broker_note:
                self.memory.log_session(f"🔌 {broker_note}")

    def _get_market_status(self) -> Dict:
        try:
            symbols = self.get_target_instruments()
            if hasattr(self.broker, "get_market_status"):
                status = self.broker.get_market_status(symbols)
                if isinstance(status, dict):
                    return status
        except Exception as e:
            self.memory.record_error("market_status", str(e))

        now = datetime.now(timezone.utc)
        scheduled = now.weekday() in TRADE_DAYS and MARKET_OPEN_HOUR <= now.hour < MARKET_CLOSE_HOUR
        return {
            "open": scheduled,
            "symbol": None,
            "tick_age_sec": None,
            "reason": "Fenêtre horaire théorique active" if scheduled else "Fenêtre horaire théorique fermée",
        }

    def is_market_open(self) -> bool:
        return bool(self._get_market_status().get("open"))

    def _max_spread_allowed(self, instrument: str) -> float:
        name = str(instrument).upper()
        if name.startswith("XAU"):
            return 45.0
        if name.startswith(("BTC", "ETH")):
            return 120.0
        return 3.0

    def _min_rr_required(self, instrument: str) -> float:
        return 1.0 if str(instrument).upper().startswith("XAU") else 1.0

    def _should_use_full_llm(self, instrument: str, signal: Dict, spread: float, chosen_rr: float, min_signal_required: int) -> bool:
        """
        Conditions assouplies pour que le LLM soit réellement utilisé.
        Ancienne logique : 5 conditions cumulatives trop restrictives → LLM jamais déclenché.
        Nouvelle logique : score suffisant + spread correct + au moins l'un des critères qualité.
        """
        details = signal.get("details", {}) or {}
        score = int(signal.get("score", 0) or 0)
        bias = abs(float(details.get("signal_bias", 0) or 0))
        trend_strength = float(details.get("trend_strength", 0) or 0)
        regime = str(details.get("market_regime", "unknown"))

        # Conditions de base non-négociables
        # On autorise l'analyse LLM un peu plus tôt pour éviter un bot silencieux.
        if score < max(2, min_signal_required - 1):
            return False
        if spread > self._max_spread_allowed(instrument):
            return False

        # Au moins l'un des critères de qualité doit être rempli
        quality_ok = (
            chosen_rr >= self._min_rr_required(instrument)
            or bias >= 1.0
            or trend_strength >= 0.06
            or regime in ("trend_bullish", "trend_bearish")
        )
        return quality_ok

    def _build_live_snapshot(self, instrument: str) -> Dict:
        candles_live = self.broker.get_candles(instrument, "M1", 60)
        candles_h1 = self.broker.get_candles(instrument, PRIMARY_TIMEFRAME, 120)
        signal = calculate_signal_score(candles_h1, instrument)
        details = signal.get("details", {}) or {}

        bid, ask = self.broker.get_current_price(instrument)
        live_price = (float(bid) + float(ask)) / 2 if (bid or ask) else float(details.get("price", 0) or 0)
        closes_base = [float(c.get("close", 0) or 0) for c in candles_live[-29:]]
        closes = closes_base + ([round(live_price, 5)] if live_price else [])
        highs = [float(c.get("high", 0) or 0) for c in candles_live[-30:]]
        lows = [float(c.get("low", 0) or 0) for c in candles_live[-30:]]

        previous_close = closes[-2] if len(closes) >= 2 else (closes[-1] if closes else 0)
        change_pct = ((live_price - previous_close) / previous_close * 100) if previous_close else 0.0
        change_5m = ((live_price - closes[-6]) / closes[-6] * 100) if len(closes) >= 6 and closes[-6] else 0.0
        spread = self.broker.get_spread_pips(instrument)

        return {
            "instrument": instrument,
            "price": round(live_price, 5),
            "bid": round(float(bid), 5),
            "ask": round(float(ask), 5),
            "support": float(details.get("support", min(lows) if lows else 0) or 0),
            "resistance": float(details.get("resistance", max(highs) if highs else 0) or 0),
            "rsi": float(details.get("rsi", 50) or 50),
            "regime": str(details.get("market_regime", "unknown")),
            "momentum_5": float(details.get("momentum_5", 0) or 0),
            "momentum_20": float(details.get("momentum_20", 0) or 0),
            "trend_strength": float(details.get("trend_strength", 0) or 0),
            "rr_buy": float(details.get("rr_buy", 0) or 0),
            "rr_sell": float(details.get("rr_sell", 0) or 0),
            "signal_bias": float(details.get("signal_bias", 0) or 0),
            "atr_pips": float(signal.get("atr_pips", 0) or 0),
            "spread": float(spread or 0),
            "price_change_pct": round(change_pct, 4),
            "price_change_5m_pct": round(change_5m, 4),
            "candle_pattern": str(details.get("candle_pattern") or "—"),
            "human_summary": str(details.get("human_summary") or "Lecture technique locale."),
            "closes": [round(v, 5) for v in closes[-30:]],
        }

    def is_cooldown_active(self, instrument: str) -> bool:
        last_time = self.last_signal_time.get(instrument)
        if not last_time:
            return False
        elapsed = (datetime.utcnow() - last_time).total_seconds() / 60
        return elapsed < SIGNAL_COOLDOWN_MINUTES

    def get_target_instruments(self) -> List[str]:
        settings = self.store.get_settings()
        max_symbols = int(settings.get("max_symbols_per_cycle", 10))
        preferred = settings.get("preferred_symbols") or []

        visible = []
        try:
            if hasattr(self.broker, "list_visible_symbols"):
                visible = self.broker.list_visible_symbols()
        except Exception as e:
            self.memory.record_error("symbols", str(e))

        if not visible:
            return list(INSTRUMENTS)[:max_symbols]

        # preferred_symbols = filtre strict (uniquement les paires en graphique)
        if preferred:
            filtered = [s for s in visible if any(s.upper() == p.upper() for p in preferred)]
            return filtered[:max_symbols] if filtered else visible[:max_symbols]

        return visible[:max_symbols]

    def run_cycle(self):
        self.memory.log_session("═══ Cycle démarré ═══")

        market_status = self._get_market_status()
        if not market_status.get("open"):
            self.memory.log_session(f"⏸️ Marché fermé - cycle ignoré | {market_status.get('reason', 'pas de cotation récente')}")
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

        if len(open_positions) >= max_open_positions:
            self.memory.log_session(f"⚠️ Max positions atteint ({max_open_positions})")
            self._check_existing_positions(open_positions)
            return

        today_pnl = self.memory.get_daily_pnl()
        if daily_loss_limit < 0 and today_pnl <= daily_loss_limit:
            self.memory.log_session(f"🛑 Perte journalière limite atteinte: ${today_pnl:.2f}")
            self._close_all_positions(open_positions, "limite de perte journalière")
            return
        # Pas d'objectif journalier fixe: on trade tant que le money management est respecté
        if today_pnl > 0:
            self.memory.log_session(f"📈 P&L jour: +${today_pnl:.2f} — on continue")

        signal_floor = max(2, int(MIN_SIGNAL_SCORE) - 1) if today_pnl < 0 else max(2, int(MIN_SIGNAL_SCORE) - 1)

        instruments = self.get_target_instruments()

        if not instruments:
            self.memory.log_session("⚠️ Aucun symbole visible dans MT5 - rien à analyser")
            return

        self.memory.log_session(f"📡 Symboles actifs: {', '.join(instruments)} | seuil signal={signal_floor}/5")

        for instrument in instruments:
            self._analyze_instrument(instrument, account, min_signal_required=signal_floor)
            time.sleep(0.2)

        self.memory.log_session("═══ Cycle terminé ═══")

    def _analyze_instrument(self, instrument: str, account: Dict, min_signal_required: int = MIN_SIGNAL_SCORE):
        if self.is_cooldown_active(instrument):
            self.memory.log_session(f"⏳ {instrument}: cooldown actif")
            return

        try:
            # Demande suffisamment de bougies pour le warm-up des indicateurs
            candles_needed = max(120, _MIN_CANDLES + 10)
            candles_h1 = self.broker.get_candles(instrument, PRIMARY_TIMEFRAME, candles_needed)
            candles_m15 = self.broker.get_candles(instrument, CONFIRM_TIMEFRAME, 80)

            if len(candles_h1) < _MIN_CANDLES:
                self.memory.log_session(
                    f"⚠️ {instrument}: données insuffisantes ({len(candles_h1)}/{_MIN_CANDLES} bougies)"
                )
                return
            if len(candles_m15) < 30:
                self.memory.log_session(f"⚠️ {instrument}: données M15 insuffisantes")
                return

            signal_h1 = calculate_signal_score(candles_h1, instrument)
            signal_m15 = calculate_signal_score(candles_m15, instrument)
            score = signal_h1["score"]
            direction = signal_h1["direction"]
            details = signal_h1.get("details", {})
            regime = details.get("market_regime", "unknown")
            trend_strength = float(details.get("trend_strength", 0) or 0)

            if signal_h1["direction"] == signal_m15["direction"] and signal_m15["score"] >= 2:
                score += 1
                self.memory.log_session(f"✅ {instrument}: alignement TF ({score}/6)")
            else:
                self.memory.log_session(f"📊 {instrument}: score H1={score}/5 | direction={direction}")
            signal_h1["score"] = score

            self.memory.log_session(
                f"🧮 {instrument}: regime={regime} | trend={trend_strength:.3f} | "
                f"RR buy={details.get('rr_buy', 0)} | RR sell={details.get('rr_sell', 0)}"
            )
            learning = self.memory.assess_setup(instrument, signal_h1)
            if learning["reasons"]:
                self.memory.log_session(f"🧠 {instrument}: mémoire → {', '.join(learning['reasons'])}")
            if learning["blocked"]:
                self.memory.log_session(f"🛡️ {instrument}: setup bloqué par la mémoire locale")
                return

            spread = self.broker.get_spread_pips(instrument)
            max_spread = self._max_spread_allowed(instrument)
            if spread > max_spread:
                self.memory.log_session(f"⚠️ {instrument}: spread trop large ({spread:.1f} pips > {max_spread:.1f})")
                return

            rr_buy = float(details.get("rr_buy", 0) or 0)
            rr_sell = float(details.get("rr_sell", 0) or 0)
            min_rr = self._min_rr_required(instrument)
            # Le RR guard sera recalculé après la décision de l'IA (sur la direction finale)

            ml_eval = self.ml_model.evaluate_signal(signal_h1, spread)
            self.memory.log_session(
                f"🧠 ML local {instrument}: p={ml_eval.get('probability', 0):.2f} | "
                f"samples={ml_eval.get('sample_count', 0)} | source={ml_eval.get('source', 'n/a')}"
            )
            signal_h1['ml_probability'] = ml_eval.get('probability', 0)
            ml_prob = float(ml_eval.get('probability', 0) or 0)
            if ml_eval.get('trained') and ml_prob < 0.35:
                inst_samples = self.store.count_ml_samples_for(instrument)
                if inst_samples >= 20:
                    self.memory.log_session(f"🛡️ {instrument}: ML bloque le trade, proba trop faible ({ml_prob:.2f})")
                    return
                else:
                    self.memory.log_session(f"⚠️ {instrument}: ML proba faible ({ml_prob:.2f}) mais données insuffisantes ({inst_samples} samples) → on continue")

            self.last_signal_time[instrument] = datetime.utcnow()
            market_ctx = (
                f"Spread actuel: {spread:.1f} pips. Heure UTC: {datetime.utcnow().hour}h. "
                f"Broker: {getattr(self.broker, 'name', 'unknown')}. "
                f"Score technique brut: {score}/5. Direction brute: {direction or 'WAIT'}. "
                f"Régime: {regime}. Trend strength: {trend_strength:.3f}. "
                f"Momentum5={details.get('momentum_5', 0)}%. Momentum20={details.get('momentum_20', 0)}%. "
                f"Support distance={details.get('distance_to_support_pips', 0)} pips. "
                f"Resistance distance={details.get('distance_to_resistance_pips', 0)} pips. "
                f"RiskReward buy={rr_buy:.2f}, sell={rr_sell:.2f}."
            )
            chosen_rr = rr_buy if direction == "BUY" else rr_sell if direction == "SELL" else max(rr_buy, rr_sell)
            use_full_llm = self._should_use_full_llm(instrument, signal_h1, spread, chosen_rr, min_signal_required)
            if not use_full_llm and direction in {"BUY", "SELL"} and score >= max(2, min_signal_required - 1):
                # Filet de sécurité: forcer ponctuellement une vraie consultation LLM
                # pour éviter de rester bloqué en mode "rapide" pendant des heures.
                use_full_llm = self.memory.get_llm_calls_today() < 2
            if use_full_llm:
                decision = self.intelligence.analyze_signal(instrument, signal_h1, account, market_ctx)
                self.memory.log_session(f"🧠 {instrument}: validation complète par le LLM local")
            else:
                decision = self.intelligence.analyze_signal(instrument, signal_h1, account, market_ctx, fast_mode=True)
                self.memory.log_session(f"⚡ {instrument}: décision rapide locale (règles + mémoire)")
            if not decision:
                return

            # Recalculer le RR guard basé sur la direction finale de l'IA (pas la direction brute du signal)
            final_dir = str(decision.get("decision", "")).upper()
            if final_dir in ("BUY", "SELL"):
                final_rr = rr_buy if final_dir == "BUY" else rr_sell
                low_rr_guard = final_rr < min_rr
            else:
                low_rr_guard = False

            # Garde-fou RR: réduit le risque (appliqué via rr_penalty dans risk_multiplier final)
            if decision.get("decision") in ["BUY", "SELL"] and low_rr_guard:
                self.memory.log_session(
                    f"⚠️ {instrument}: RR faible ({final_rr:.2f} < {min_rr:.2f}) → risque réduit ×0.6"
                )

            if regime == "range" and score < min_signal_required and decision.get("decision") in ["BUY", "SELL"]:
                self.memory.log_session(
                    f"🛡️ {instrument}: ordre bloqué, marché en range avec score faible ({score}/{min_signal_required})"
                )
                decision = {
                    **decision,
                    "decision": "WAIT",
                    "reasoning": f"Marché range + score insuffisant ({score}/{min_signal_required})",
                }

            self.store.record_signal_sample(instrument, signal_h1, spread, decision)

            ml_boost = 1.1 if float(ml_eval.get('probability', 0) or 0) >= 0.60 else 1.0
            rr_penalty = 0.6 if low_rr_guard and decision.get("decision") in ["BUY", "SELL"] else 1.0
            decision["risk_multiplier"] = round(learning["risk_multiplier"] * ml_boost * rr_penalty, 2)
            instrument_positions = [p for p in self.broker.get_open_positions() if str(p.get("instrument", "")).upper() == instrument.upper()]

            if decision["decision"] in ["BUY", "SELL"]:
                if self._manage_existing_position(instrument, instrument_positions, decision):
                    return
                self._execute_trade(instrument, decision, signal_h1, account)
            else:
                if instrument_positions:
                    self.memory.log_session(f"🧭 {instrument}: pas de nouveau trade, position existante surveillée automatiquement")
                self.memory.log_session(f"⏸️ {instrument}: IA dit WAIT - {decision.get('reasoning', '')[:90]}")

        except Exception as e:
            self.memory.record_error(f"analysis:{instrument}", str(e))
            self.memory.log_session(f"❌ Erreur analyse {instrument}: {e}")

    def _execute_trade(self, instrument: str, decision: Dict, signal: Dict, account: Dict):
        direction = decision["decision"]
        atr = max(6, int(round(float(signal.get("atr_pips", 20) or 20))))
        raw_sl = int(decision.get("stop_loss_pips", atr) or atr)
        sl_pips = max(atr, raw_sl)
        rr_ratio = max(1.5, tp_pips_raw / sl_pips if (tp_pips_raw := int(decision.get("take_profit_pips", sl_pips * 2) or sl_pips * 2)) and sl_pips else 2.0)
        tp_pips = max(sl_pips, int(sl_pips * rr_ratio))
        confidence = float(decision.get("confidence", 0.5))
        risk_multiplier = float(decision.get("risk_multiplier", 1.0))

        settings = self.store.get_settings()
        balance = max(1.0, account.get("balance", 0))
        max_risk_pct = float(settings.get("max_risk_per_trade", MAX_RISK_PER_TRADE))
        risk_usd = max(0.5, balance * max_risk_pct * risk_multiplier)

        # --- Money management: cap SL so actual risk stays within budget ---
        pip_value = getattr(self.broker, '_pip_value_per_lot', lambda x: 10.0)(instrument)
        vol_min = getattr(self.broker, '_volume_min', lambda x: 0.01)(instrument)
        min_risk_at_sl = vol_min * sl_pips * pip_value
        max_allowed_risk = balance * 0.05  # Hard cap 5% of balance

        if min_risk_at_sl > risk_usd and min_risk_at_sl > max_allowed_risk:
            # SL too wide for this capital at min volume → reduce SL, keep RR
            new_sl = max(6, int(max_allowed_risk / max(0.001, vol_min * pip_value)))
            self.memory.log_session(
                f"⚠️ Money mgmt: SL {sl_pips}→{new_sl}p (capital ${balance:.0f}, risque max ${max_allowed_risk:.2f})"
            )
            sl_pips = new_sl
            tp_pips = max(sl_pips, int(sl_pips * rr_ratio))

        volume = self.broker.calculate_volume(instrument, risk_usd, sl_pips)
        actual_risk = volume * sl_pips * pip_value

        self.memory.log_session(
            f"📈 Ordre: {direction} {instrument} | vol={volume} | SL={sl_pips}p | TP={tp_pips}p | risque=${actual_risk:.2f}"
        )

        order = self.broker.place_market_order(
            instrument=instrument,
            direction=direction,
            volume=volume,
            stop_loss_pips=sl_pips,
            take_profit_pips=tp_pips,
            comment=f"LOCAL|{signal.get('pattern', '')[:20]}|{int(confidence * 100)}"
        )

        if order:
            trade_id = self.memory.add_trade({
                "instrument": instrument,
                "direction": direction,
                "volume": volume,
                "entry_price": order.get("entry_price", 0.0),
                "stop_loss": order.get("stop_loss", 0.0),
                "take_profit": order.get("take_profit", 0.0),
                "broker_id": order.get("broker_id"),
                "pattern": signal.get("pattern"),
                "signal_score": signal.get("score", 0),
                "confidence": confidence,
                "sl_pips": sl_pips,
                "tp_pips": tp_pips,
                "risk_usd": round(actual_risk, 2),
                "reasoning": decision.get("reasoning", ""),
                "status": order.get("status", "open")
            })
            self.memory.log_session(
                f"✅ Trade #{trade_id} créé: {direction} {instrument} vol={volume} @ {order.get('entry_price', 0):.5f} [{order.get('status', 'open')}]"
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

    def _close_all_positions(self, positions: List[Dict], reason: str):
        for pos in positions:
            try:
                pnl = self.broker.close_position(pos.get("instrument"))
                self.memory.log_session(
                    f"🔒 Fermeture auto {pos.get('instrument')} | raison: {reason} | pnl={float(pnl or 0):.2f}"
                )
            except Exception as e:
                self.memory.log_session(f"❌ Fermeture auto échouée {pos.get('instrument')}: {e}")

    def _manage_existing_position(self, instrument: str, positions: List[Dict], decision: Dict) -> bool:
        if not positions:
            return False

        wanted = str(decision.get("decision", "WAIT")).upper()
        for pos in positions:
            current_dir = str(pos.get("direction", "")).upper()
            if current_dir == wanted:
                self.memory.log_session(f"🟢 {instrument}: position {current_dir} déjà ouverte, pas de doublon")
                return True
            if current_dir and wanted in {"BUY", "SELL"} and current_dir != wanted:
                try:
                    pnl = self.broker.close_position(instrument)
                    self.memory.log_session(
                        f"🔄 {instrument}: fermeture auto {current_dir} puis inversion vers {wanted} | pnl={float(pnl or 0):.2f}"
                    )
                except Exception as e:
                    self.memory.log_session(f"❌ {instrument}: impossible de fermer avant inversion: {e}")
                    return True
        return False

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
        candles_needed = max(120, _MIN_CANDLES + 10)
        candles = self.broker.get_candles(target, PRIMARY_TIMEFRAME, candles_needed)
        signal = calculate_signal_score(candles, target)

        spread = self.broker.get_spread_pips(target)
        context = f"Mode test dashboard. Spread actuel: {spread:.1f} pips."
        # Le test IA du dashboard doit vérifier le moteur réel (LLM), pas uniquement le fallback rapide.
        decision = self.intelligence.analyze_signal(target, signal, account, context, fast_mode=False)
        ml_eval = self.ml_model.evaluate_signal(signal, spread)
        signal["ml_probability"] = ml_eval.get("probability", 0)
        if isinstance(decision, dict):
            decision["ml_probability"] = ml_eval.get("probability", 0)
            decision["ml_trained"] = ml_eval.get("trained", False)
        return {
            "instrument": target,
            "signal": signal,
            "decision": decision,
            "provider": self.intelligence.provider,
            "spread": spread,
            "ml_eval": ml_eval,
            "market_snapshot": self._build_live_snapshot(target),
        }

    def get_status(self, focus_symbol: str = "") -> Dict:
        try:
            account = self.broker.get_account_summary()
            positions = self.broker.get_open_positions()
        except Exception as e:
            self.memory.record_error("status", str(e))
            account = {"balance": 0, "unrealized_pnl": 0, "nav": 0, "open_trades": 0, "connected": False}
            positions = []

        runtime_settings = self.store.get_settings()
        ml_stats = self.store.get_ml_stats()
        ml_history = self.store.get_recent_ml_samples(28)
        ml_model_state = self.ml_model.get_status()
        llm_calls = self.memory.get_llm_calls_today()
        active_symbols = self.get_target_instruments()
        market_status = self._get_market_status()

        raw_logs = self.memory.memory.get("session_log", [])[-80:]
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "market_open": bool(market_status.get("open")),
            "market_status": market_status,
            "active_symbols": active_symbols,
            "account": account,
            "open_positions": positions,
            "daily_pnl": self.memory.get_daily_pnl(),
            "total_pnl": self.memory.memory.get("total_pnl", 0),
            "win_rate": self.memory.get_win_rate(),
            "total_trades": self.memory.memory.get("total_trades", 0),
            "llm_calls_today": llm_calls,
            "api_calls_today": llm_calls,
            "recent_trades": self.memory.get_recent_trades(5),
            "session_log": raw_logs[-20:],
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
            "ml_model_state": ml_model_state,
            "ml_history": ml_history,
            "learned_filters": self.memory.memory.get("learned_filters", [])[-5:],
            "runtime_mode": "local-only",
        }