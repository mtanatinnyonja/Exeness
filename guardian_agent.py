"""
Agent Gardien — Surveille les positions ouvertes en continu.
Autonome, décide de HOLD/CLOSE/TIGHTEN sur ses propres observations.
"""

import asyncio
from typing import Dict, List
from agent_framework import Agent
from mt5_bridge import build_broker
from signal_engine import calculate_signal_score
from settings import PRIMARY_TIMEFRAME


class GuardianAgent(Agent):
    """Gardien autonome — Surveille positions, prend décisions HOLD/CLOSE/TIGHTEN."""
    
    def __init__(self):
        super().__init__("GuardianAgent")
        self.broker = build_broker()
        self.check_count = 0
    
    async def on_startup(self):
        """Initialisation."""
        self.log("INFO", "Démarré. Surveillance en continu...")
        await self.bus.subscribe(self.name, ["trade_opened", "position_alert"])
    
    async def run(self):
        """Boucle autonome — surveille positions en continu."""
        while self.running:
            await self._check_all_positions()
            self.check_count += 1
            await asyncio.sleep(5)  # Check toutes les 5s
    
    async def _check_all_positions(self):
        """Surveille toutes les positions ouvertes."""
        try:
            positions = self.broker.get_open_positions()
            if not positions:
                return
            
            for position in positions:
                await self._monitor_position(position)
        
        except Exception as e:
            self.log("ERROR", f"Check positions: {str(e)[:100]}")
    
    async def _monitor_position(self, position: Dict):
        """Surveille une position et décide action."""
        instrument = position.get("instrument", "?")
        direction = position.get("direction", "?")
        entry = float(position.get("entry_price", 0))
        current = float(position.get("current_price", 0))
        unrealized_pnl = float(position.get("unrealized_pnl", 0))
        
        try:
            # Récupérer le signal actuel
            candles = self.broker.get_candles(instrument, PRIMARY_TIMEFRAME, 50)
            if len(candles) < 20:
                return
            
            signal = calculate_signal_score(candles, instrument)
            signal_direction = signal.get("direction", "WAIT")
            signal_score = signal.get("score", 0)
            
            # Logique de décision
            action = "HOLD"
            reason = "position stable"
            
            # 1. Reversal détecté → CLOSE
            if direction == "BUY" and signal_direction == "SELL" and signal_score >= 3:
                action = "CLOSE"
                reason = f"reversal détecté (signal SELL {signal_score}/5)"
            elif direction == "SELL" and signal_direction == "BUY" and signal_score >= 3:
                action = "CLOSE"
                reason = f"reversal détecté (signal BUY {signal_score}/5)"
            
            # 2. Perte trop grande → CLOSE
            elif unrealized_pnl < -10.0:
                action = "CLOSE"
                reason = f"perte ${unrealized_pnl:.2f}"
            
            # 3. Objectif atteint → CLOSE
            elif unrealized_pnl > 20.0:
                action = "CLOSE"
                reason = f"objectif atteint: ${unrealized_pnl:.2f}"
            
            # Log
            emoji = {"HOLD": "✅", "CLOSE": "🔴", "TIGHTEN": "🔄"}.get(action, "?")
            self.log("INFO", f"{emoji} {instrument} {direction}: {action} ({reason}) | P&L: ${unrealized_pnl:+.2f}")
            
            # Envoyer l'action
            if action != "HOLD":
                await self.send_message(
                    "ExecutionAgent",
                    "guardian_action",
                    {
                        "instrument": instrument,
                        "action": action,
                        "reason": reason,
                        "unrealized_pnl": unrealized_pnl,
                    }
                )
        
        except Exception as e:
            self.log("ERROR", f"{instrument}: {str(e)[:100]}")
