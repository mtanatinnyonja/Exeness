""" 
Agent Risk Manager — Spécialisé XAUUSDm uniquement.
Rejette tout signal non-XAU. Paramètres SL/TP calibrés pour la volatilité de l'or.
"""

import asyncio
from typing import Dict, Any
from agent_framework import Agent
from market_protection import run_all_protections
from economic_calendar import EconomicCalendar
from mt5_bridge import build_broker
from learning_store import AgentMemory
from runtime_db import RuntimeStore
from settings import DAILY_TARGET


class RiskAgent(Agent):
    """Risk Manager XAUUSDm — Valide/bloque les signaux gold."""
    
    def __init__(self):
        super().__init__("RiskAgent")
        self.broker = build_broker()
        self.calendar = EconomicCalendar()
        self.memory = AgentMemory()
        self.processed_signals = 0
        self.min_signal_score = 3      # Score minimum pour XAU
        self.min_rr = 1.5              # RR minimum (ex: SL=20p TP=30p)
        self.xau_spread_limit = 8.0    # Spread max XAU en pips (Exness ~3p normal)

    def _reject(self, instrument, signal_id, reason):
        """Shortcut pour envoyer un rejet."""
        return self.send_message("*", "risk_decision", {
            "instrument": instrument,
            "approved": False,
            "signal_id": signal_id,
            "reason": reason,
        })
    
    async def on_startup(self):
        """Initialisation."""
        self.log("INFO", "Démarré. En attente de signaux...")
        await self.bus.subscribe(self.name, ["signal"])
    
    async def run(self):
        """Boucle autonome — évalue risques des signaux reçus."""
        while self.running:
            message = await self.wait_for_message(timeout=2.0)
            
            if message and message.event_type == "signal":
                await self._evaluate_risk(message.payload)

            self.write_heartbeat()
            await asyncio.sleep(0.1)
    
    async def _evaluate_risk(self, signal_data: Dict[str, Any]):
        """Évalue le risque d'un signal XAUUSDm et décide approuver/bloquer."""
        instrument = signal_data.get("instrument", "?")
        direction = signal_data.get("direction", "?")
        signal_id = signal_data.get("signal_id", "")

        # Rejet immédiat si ce n'est pas XAUUSDm
        if str(instrument).upper() != "XAUUSDM":
            await self._reject(instrument, signal_id, f"{instrument} ignoré — système spécialisé XAUUSDm")
            return

        try:
            # === OBJECTIF JOURNALIER ===
            try:
                store = RuntimeStore()
                daily_target = float(store.get("daily_target") or DAILY_TARGET)
                daily_pnl = self.memory.get_daily_pnl()
            except Exception:
                daily_target = DAILY_TARGET
                daily_pnl = 0.0

            if daily_target > 0 and daily_pnl >= daily_target:
                await self._reject(instrument, signal_id,
                    f"✅ Objectif journalier atteint ({daily_pnl:+.2f}$ / {daily_target:.2f}$) — pause")
                self.log("INFO", f"XAU: Bloqué — objectif journalier atteint ({daily_pnl:+.2f}$)")
                return

            # Mode conservateur quand 75%+ de l'objectif atteint
            conservative_mode = daily_target > 0 and daily_pnl >= daily_target * 0.75
            effective_min_score = 4 if conservative_mode else self.min_signal_score
            effective_min_rr = 2.0 if conservative_mode else self.min_rr
            if conservative_mode:
                self.log("INFO", f"XAU: Mode conservateur ({daily_pnl:+.2f}$ / {daily_target:.2f}$) — score≥4, RR≥2.0")

            # === SCORE ===
            score = int(signal_data.get("score", 0) or 0)
            if score < effective_min_score:
                await self._reject(instrument, signal_id, f"Score insuffisant: {score}/5")
                self.log("INFO", f"XAU: Rejet score ({score}/5)")
                return

            # === SPREAD XAU ===
            spread_signal = float(signal_data.get("spread", 0.0) or 0.0)
            if spread_signal > self.xau_spread_limit:
                await self._reject(instrument, signal_id,
                    f"Spread XAU trop élevé: {spread_signal:.1f}p > {self.xau_spread_limit:.1f}p")
                self.log("WARN", f"XAU: Bloqué spread ({spread_signal:.1f}p)")
                return

            # === CONFIRMATION MTF ===
            confirm = signal_data.get("signal_confirm") or {}
            if confirm and confirm.get("direction") and str(confirm.get("direction")).upper() != str(direction).upper():
                await self._reject(instrument, signal_id, "Conflit H1/M15")
                self.log("INFO", "XAU: Bloqué conflit de confirmation")
                return

            # === RATIO RISQUE/RENDEMENT ===
            details = signal_data.get("details", {}) or {}
            direction_up = str(direction).upper()
            rr_key = "rr_buy" if direction_up == "BUY" else "rr_sell"
            rr = float(details.get(rr_key, 0.0) or 0.0)
            if 0 < rr < effective_min_rr:
                await self._reject(instrument, signal_id, f"RR insuffisant: {rr:.2f} < {effective_min_rr}")
                self.log("INFO", f"XAU: Bloqué RR {rr:.2f}")
                return

            quality_score = float(details.get("quality_score", 0.0) or 0.0)
            if quality_score < 0.35:
                await self._reject(instrument, signal_id, f"Qualité signal insuffisante ({quality_score:.2f})")
                self.log("INFO", f"XAU: Bloqué quality_score ({quality_score:.2f})")
                return

            # === NEWS ÉCONOMIQUES ===
            try:
                news_check = self.calendar.should_pause_trading(instrument)
                if news_check.get("pause"):
                    await self._reject(instrument, signal_id, f"News: {news_check['reason']}")
                    self.log("WARN", f"XAU: Bloqué par news")
                    return
            except Exception as e:
                self.log("WARN", f"Calendrier indisponible: {str(e)[:80]}")

            # === PROTECTIONS MARCHÉ ===
            candles = self.broker.get_candles("XAUUSDm", "H1", 60)
            if candles:
                spread = self.broker.get_spread_pips("XAUUSDm")
                pip_size = self.broker._pip_size("XAUUSDm")
                protections = run_all_protections(
                    "XAUUSDm", candles, spread, pip_size,
                    price=candles[-1]["close"]
                )
                if protections.get("blocked"):
                    blocks = protections.get("hard_blocks", [])
                    await self._reject(instrument, signal_id, f"Protections: {'; '.join(blocks)}")
                    self.log("WARN", f"XAU: Bloqué par protections")
                    return

            # === CALCUL SL/TP XAU ===
            # XAU : ATR typique H1 = 15-25 pips. SL = 1.5×ATR, TP = 3×ATR
            atr = float(details.get("atr_pips", 20))
            if direction_up == "BUY":
                sl_pips = int(details.get("distance_to_support_pips", atr * 1.5))
                tp_pips = int(details.get("distance_to_resistance_pips", atr * 3.0))
            else:
                sl_pips = int(details.get("distance_to_resistance_pips", atr * 1.5))
                tp_pips = int(details.get("distance_to_support_pips", atr * 3.0))
            sl_pips = max(sl_pips, max(15, int(atr * 1.0)))  # minimum 15 pips sur XAU
            tp_pips = max(tp_pips, sl_pips * 2)               # minimum RR 1:2

            quality = float(details.get("quality_score", 0.5))
            sig_score = signal_data.get("score", 3)
            risk_score = max(1, min(5, round(sig_score * quality * 2)))

            await self.send_message(
                "*", "risk_decision",
                {
                    "instrument": instrument,
                    "approved": True,
                    "signal_id": signal_id,
                    "risk_score": risk_score,
                    "approved_at": asyncio.get_event_loop().time(),
                    "sl_pips": sl_pips,
                    "tp_pips": tp_pips,
                }
            )
            self.log("INFO", f"XAU ✅ Approuvé {direction_up} | score={sig_score}/5 risk={risk_score}/5 RR={rr:.2f} SL={sl_pips}p TP={tp_pips}p")
            self.processed_signals += 1

        except Exception as e:
            self.log("ERROR", f"XAU: {str(e)[:100]}")
