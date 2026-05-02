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
            
            await asyncio.sleep(0.1)
    
    async def _evaluate_risk(self, signal_data: Dict[str, Any]):
        """Évalue le risque d'un signal et décide approuver/bloquer."""
        instrument = signal_data.get("instrument", "?")
        direction = signal_data.get("direction", "?")
        
        try:
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
            except Exception:
                pass
            
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
            
            # Approuver le signal
            await self.send_message(
                "*",
                "risk_decision",
                {
                    "instrument": instrument,
                    "approved": True,
                    "risk_score": 3,
                    "sl_pips": int(signal_data.get("details", {}).get("atr_pips", 20) * 1.5),
                    "tp_pips": int(signal_data.get("details", {}).get("atr_pips", 20) * 3),
                }
            )
            self.log("INFO", f"{instrument}: Approuvé (risque modéré)")
            self.processed_signals += 1
        
        except Exception as e:
            self.log("ERROR", f"{instrument}: {str(e)[:100]}")
