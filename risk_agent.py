"""
Agent Risk Manager — Évalue les risques des signaux reçus.
Autonome, reçoit des signaux et valide/bloque.
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
    """Risk Manager autonome — Reçoit signaux, évalue risques, approuve/bloque."""
    
    def __init__(self):
        super().__init__("RiskAgent")
        self.broker = build_broker()
        self.calendar = EconomicCalendar()
        self.memory = AgentMemory()
        self.processed_signals = 0
        self.min_signal_score = 3
        self.min_rr = 1.5  # Ratio risque/rendement minimum requis
        self.max_spread_by_instrument = {
            "BTC": 80.0,
            "XAU": 35.0,
            "FX": 5.0,
        }

    def _spread_limit(self, instrument: str) -> float:
        inst = str(instrument).upper()
        if inst.startswith("BTC"):
            return self.max_spread_by_instrument["BTC"]
        if inst.startswith("XAU"):
            return self.max_spread_by_instrument["XAU"]
        return self.max_spread_by_instrument["FX"]
    
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
        """Évalue le risque d'un signal et décide approuver/bloquer."""
        instrument = signal_data.get("instrument", "?")
        direction = signal_data.get("direction", "?")
        signal_id = signal_data.get("signal_id", "")
        
        try:
            # === CONTRÔLE OBJECTIF JOURNALIER ===
            try:
                store = RuntimeStore()
                daily_target = float(store.get("daily_target") or DAILY_TARGET)
                daily_pnl = self.memory.get_daily_pnl()
            except Exception:
                daily_target = DAILY_TARGET
                daily_pnl = 0.0

            if daily_target > 0 and daily_pnl >= daily_target:
                await self.send_message(
                    "*",
                    "risk_decision",
                    {
                        "instrument": instrument,
                        "approved": False,
                        "signal_id": signal_id,
                        "reason": f"Objectif journalier atteint ({daily_pnl:+.2f}$ / {daily_target:.2f}$) — pause jusqu'à demain",
                    }
                )
                self.log("INFO", f"{instrument}: Bloqué — objectif journalier atteint ({daily_pnl:+.2f}$)")
                return

            # Mode conservateur : 75%-100% du target atteint → filtre plus strict
            conservative_mode = daily_target > 0 and daily_pnl >= daily_target * 0.75
            effective_min_score = 4 if conservative_mode else self.min_signal_score
            effective_min_rr = 2.0 if conservative_mode else self.min_rr
            if conservative_mode:
                self.log("INFO", f"{instrument}: Mode conservateur ({daily_pnl:+.2f}$ / {daily_target:.2f}$) — score≥4, RR≥2.0")

            score = int(signal_data.get("score", 0) or 0)
            if score < effective_min_score:
                await self.send_message(
                    "*",
                    "risk_decision",
                    {
                        "instrument": instrument,
                        "approved": False,
                        "signal_id": signal_id,
                        "reason": f"Score insuffisant: {score}/5",
                    }
                )
                self.log("INFO", f"{instrument}: Rejet score ({score}/5)")
                return

            spread_signal = float(signal_data.get("spread", 0.0) or 0.0)
            spread_limit = self._spread_limit(instrument)
            if spread_signal > spread_limit:
                await self.send_message(
                    "*",
                    "risk_decision",
                    {
                        "instrument": instrument,
                        "approved": False,
                        "signal_id": signal_id,
                        "reason": f"Spread trop élevé: {spread_signal:.1f}p > {spread_limit:.1f}p",
                    }
                )
                self.log("WARN", f"{instrument}: Bloqué spread ({spread_signal:.1f}p)")
                return

            confirm = signal_data.get("signal_confirm") or {}
            if confirm and confirm.get("direction") and str(confirm.get("direction")).upper() != str(direction).upper():
                await self.send_message(
                    "*",
                    "risk_decision",
                    {
                        "instrument": instrument,
                        "approved": False,
                        "signal_id": signal_id,
                        "reason": "Conflit H1/M15",
                    }
                )
                self.log("INFO", f"{instrument}: Bloqué conflit de confirmation")
                return

            # RR minimum — évite les trades à faible espérance mathématique
            details = signal_data.get("details", {}) or {}
            direction_up = str(direction).upper()
            rr_key = "rr_buy" if direction_up == "BUY" else "rr_sell"
            rr = float(details.get(rr_key, 0.0) or 0.0)
            if 0 < rr < effective_min_rr:
                await self.send_message(
                    "*",
                    "risk_decision",
                    {
                        "instrument": instrument,
                        "approved": False,
                        "signal_id": signal_id,
                        "reason": f"RR insuffisant: {rr:.2f} < {effective_min_rr}",
                    }
                )
                self.log("INFO", f"{instrument}: Bloqué RR {rr:.2f}")
                return

            quality_score = float(details.get("quality_score", 0.0) or 0.0)
            if quality_score < 0.35:
                await self.send_message(
                    "*",
                    "risk_decision",
                    {
                        "instrument": instrument,
                        "approved": False,
                        "signal_id": signal_id,
                        "reason": "qualité signal insuffisante",
                    }
                )
                self.log("INFO", f"{instrument}: Bloqué quality_score ({quality_score:.2f})")
                return

            # Check news
            try:
                news_check = self.calendar.should_pause_trading(instrument)
                if news_check.get("pause"):
                    await self.send_message(
                        "*",
                        "risk_decision",
                        {
                            "instrument": instrument,
                            "approved": False,
                            "signal_id": signal_id,
                            "reason": f"News: {news_check['reason']}"
                        }
                    )
                    self.log("WARN", f"{instrument}: Bloqué par news")
                    return
            except Exception as e:
                self.log("WARN", f"Calendrier indisponible: {str(e)[:80]}")
            
            # Check protections
            candles = self.broker.get_candles(instrument, "H1", 60)
            if candles:
                spread = self.broker.get_spread_pips(instrument)
                pip_size = self.broker._pip_size(instrument)
                protections = run_all_protections(
                    instrument, candles, spread, pip_size,
                    price=candles[-1]["close"]
                )
                
                if protections.get("blocked"):
                    blocks = protections.get("hard_blocks", [])
                    await self.send_message(
                        "*",
                        "risk_decision",
                        {
                            "instrument": instrument,
                            "approved": False,
                            "signal_id": signal_id,
                            "reason": f"Protections: {'; '.join(blocks)}"
                        }
                    )
                    self.log("WARN", f"{instrument}: Bloqué par protections")
                    return
            
            # Approuver le signal avec score/SL/TP dynamiques
            details = signal_data.get("details", {})
            quality = signal_data.get("details", {}).get("quality_score", 0.5)
            sig_score = signal_data.get("score", 3)
            risk_score = max(1, min(5, round(sig_score * quality * 2)))

            direction = signal_data.get("direction", "BUY")
            atr = details.get("atr_pips", 20)
            if direction == "BUY":
                sl_pips = int(details.get("distance_to_support_pips", atr * 1.5))
                tp_pips = int(details.get("distance_to_resistance_pips", atr * 3.0))
            else:
                sl_pips = int(details.get("distance_to_resistance_pips", atr * 1.5))
                tp_pips = int(details.get("distance_to_support_pips", atr * 3.0))
            sl_pips = max(sl_pips, int(atr * 1.0))  # minimum de sécurité

            await self.send_message(
                "*",
                "risk_decision",
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
            self.log("INFO", f"{instrument}: Approuvé (risk_score={risk_score}/5, rr={rr:.2f}, q={quality_score:.2f})")
            self.processed_signals += 1
        
        except Exception as e:
            self.log("ERROR", f"{instrument}: {str(e)[:100]}")
