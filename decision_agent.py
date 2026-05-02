"""
Agent Décideur — Reçoit signaux + évaluations risques et prend décision finale.
Autonome, vote et décide BUY/SELL basé sur consensus.
"""

import asyncio
from typing import Dict, Any, Optional
from agent_framework import Agent


class DecisionAgent(Agent):
    """Décideur autonome — Synthétise signaux et risques pour décision finale."""
    
    def __init__(self):
        super().__init__("DecisionAgent")
        self.pending_signals: Dict[str, Dict[str, Any]] = {}  # instrument -> signal_data
        self.decisions_made = 0
    
    async def on_startup(self):
        """Initialisation."""
        self.log("INFO", "Démarré. En attente de signaux et approvals...")
        await self.bus.subscribe(self.name, ["signal", "risk_decision"])
    
    async def run(self):
        """Boucle autonome — synthétise et décide."""
        while self.running:
            message = await self.wait_for_message(timeout=1.0)
            
            if message and message.event_type == "signal":
                instrument = message.payload.get("instrument", "?")
                self.pending_signals[instrument] = message.payload
                self.log("DEBUG", f"{instrument}: Signal en attente d'approval risque")
            
            elif message and message.event_type == "risk_decision":
                await self._process_risk_decision(message.payload)
            
            await asyncio.sleep(0.1)
    
    async def _process_risk_decision(self, risk_data: Dict[str, Any]):
        """Traite une décision de risque et décide si on trade."""
        instrument = risk_data.get("instrument", "?")
        approved = risk_data.get("approved", False)
        
        # Vérifier si on a le signal correspondant
        if instrument not in self.pending_signals:
            return
        
        signal_data = self.pending_signals.pop(instrument)
        
        if not approved:
            reason = risk_data.get("reason", "risque trop élevé")
            self.log("INFO", f"{instrument}: Rejeté — {reason}")
            return
        
        # DECISION FINALE : Trade approuvé
        direction = signal_data.get("direction", "?")
        
        # Décision finale
        decision = {
            "instrument": instrument,
            "direction": direction,
            "confidence": float(signal_data.get("score", 0)) / 5.0,
            "sl_pips": risk_data.get("sl_pips", 30),
            "tp_pips": risk_data.get("tp_pips", 60),
            "signal_score": signal_data.get("score", 0),
            "market_context": signal_data.get("market_context", {}),
        }
        
        # Envoyer à ExecutionAgent pour exécution
        await self.send_message(
            "ExecutionAgent",
            "buy_signal" if direction == "BUY" else "sell_signal",
            decision
        )
        
        self.log("INFO", f"✅ {instrument}: DÉCISION {direction} (conf {decision['confidence']:.1%})")
        self.decisions_made += 1
