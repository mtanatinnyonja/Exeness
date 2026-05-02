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


class RiskAgent(Agent):
    """Risk Manager autonome — Reçoit signaux, évalue risques, approuve/bloque."""
    
    def __init__(self):
        super().__init__("RiskAgent")
        self.broker = build_broker()
        self.calendar = EconomicCalendar()
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
        
        try:
            score = int(signal_data.get("score", 0) or 0)
            if score < self.min_signal_score:
                await self.send_message(
                    "*",
                    "risk_decision",
                    {
                        "instrument": instrument,
                        "approved": False,
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
            if 0 < rr < self.min_rr:
                await self.send_message(
                    "*",
                    "risk_decision",
                    {
                        "instrument": instrument,
                        "approved": False,
                        "reason": f"RR insuffisant: {rr:.2f} < {self.min_rr}",
                    }
                )
                self.log("INFO", f"{instrument}: Bloqué RR {rr:.2f}")
                return

            quality_score = float(details.get("quality_score", 0.0) or 0.0)
            if quality_score < 0.4:
                await self.send_message(
                    "*",
                    "risk_decision",
                    {
                        "instrument": instrument,
                        "approved": False,
                        "reason": f"Qualité insuffisante: {quality_score:.2f} < 0.40",
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
                            "reason": f"News: {news_check['reason']}"
                        }
                    )
                    self.log("WARN", f"{instrument}: Bloqué par news")
                    return
            except Exception as e:
                self.log("WARN", f"Calendrier: {e}")
            
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
                            "reason": f"Protections: {'; '.join(blocks)}"
                        }
                    )
                    self.log("WARN", f"{instrument}: Bloqué par protections")
                    return
            
            # Approuver le signal avec SL/TP basés sur niveaux S/R + plancher ATR
            details = signal_data.get("details", {}) or {}
            atr_pips = float(details.get("atr_pips", 0.0) or 0.0)
            # Fallback si ATR trop faible
            if atr_pips < 5.0:
                instrument_upper = str(instrument).upper()
                if instrument_upper.startswith("BTC"):
                    atr_pips = 120.0
                elif instrument_upper.startswith("XAU"):
                    atr_pips = 30.0
                else:
                    atr_pips = 15.0

            distance_to_support = float(details.get("distance_to_support_pips", 0.0) or 0.0)
            distance_to_resistance = float(details.get("distance_to_resistance_pips", 0.0) or 0.0)
            min_stop_pips = max(atr_pips * 1.0, 6.0)

            if direction_up == "BUY":
                sl_from_structure = distance_to_support
                tp_from_structure = distance_to_resistance
            else:
                sl_from_structure = distance_to_resistance
                tp_from_structure = distance_to_support

            sl_pips = max(int(round(sl_from_structure)), int(round(min_stop_pips)))
            tp_pips = max(int(round(tp_from_structure)), int(round(min_stop_pips)))

            rr_component = max(0.0, min(rr / 3.0, 1.0))
            quality_component = max(0.0, min(quality_score / 1.5, 1.0))
            risk_score = int(round(1 + (4 * ((0.6 * quality_component) + (0.4 * rr_component)))))
            risk_score = max(1, min(5, risk_score))

            await self.send_message(
                "*",
                "risk_decision",
                {
                    "instrument": instrument,
                    "approved": True,
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
