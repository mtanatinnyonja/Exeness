"""
Agent Décideur — Reçoit signaux + évaluations risques et prend décision finale.
Autonome, vote et décide BUY/SELL basé sur consensus.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional
from agent_framework import Agent


class DecisionAgent(Agent):
    """Décideur autonome — Synthétise signaux et risques pour décision finale."""
    
    def __init__(self):
        super().__init__("DecisionAgent")
        # instrument -> {"payload": signal_data, "timestamp": datetime(UTC)}
        self.pending_signals: Dict[str, Dict[str, Any]] = {}
        self.decisions_made = 0
        self.expired_signals = 0
        self.min_confidence = 0.60
        self.min_risk_score = 3
        self.signal_ttl_seconds = 90
        self.instrument_cooldown_seconds = 120
        self.last_decision_at: Dict[str, datetime] = {}
    
    async def on_startup(self):
        """Initialisation."""
        self.log("INFO", "Démarré. En attente de signaux et approvals...")
        await self.bus.subscribe(self.name, ["signal", "risk_decision"])
    
    async def run(self):
        """Boucle autonome — synthétise et décide."""
        while self.running:
            self._cleanup_expired_signals()
            message = await self.wait_for_message(timeout=1.0)
            
            if message and message.event_type == "signal":
                instrument = message.payload.get("instrument", "?")
                now_utc = datetime.now(timezone.utc)
                if instrument in self.pending_signals:
                    self.log("INFO", f"signal ignoré pour {instrument} — signal déjà en attente")
                else:
                    self.pending_signals[instrument] = {
                        "payload": dict(message.payload),
                        "signal_id": message.payload.get("signal_id", ""),
                        "timestamp": now_utc,
                    }
                    self.log("DEBUG", f"{instrument}: Signal en attente d'approval risque")
            
            elif message and message.event_type == "risk_decision":
                await self._process_risk_decision(message.payload)

            self.write_heartbeat({"expired_signals": self.expired_signals})
            await asyncio.sleep(0.1)

    def _cleanup_expired_signals(self) -> None:
        """Supprime les signaux périmés sans bloquer la boucle asynchrone."""
        now_utc = datetime.now(timezone.utc)
        expired_instruments = []
        for instrument, item in self.pending_signals.items():
            ts = item.get("timestamp")
            if isinstance(ts, datetime):
                if (now_utc - ts).total_seconds() > self.signal_ttl_seconds:
                    expired_instruments.append(instrument)
            else:
                # Défensif: si timestamp absent/invalide, on expire immédiatement.
                expired_instruments.append(instrument)

        for instrument in expired_instruments:
            self.pending_signals.pop(instrument, None)
            self.expired_signals += 1
            self.log("WARN", f"signal {instrument} expiré après 90s sans réponse RiskAgent")
    
    async def _process_risk_decision(self, risk_data: Dict[str, Any]):
        """Traite une décision de risque et décide si on trade."""
        instrument = risk_data.get("instrument", "?")
        approved = risk_data.get("approved", False)
        
        # Vérifier si on a le signal correspondant
        if instrument not in self.pending_signals:
            return

        # Vérifier que la décision de risque correspond bien au signal en attente
        signal_item = self.pending_signals[instrument]
        pending_signal_id = signal_item.get("signal_id", "")
        incoming_signal_id = risk_data.get("signal_id", "")
        if pending_signal_id and incoming_signal_id and pending_signal_id != incoming_signal_id:
            self.log("WARN", f"{instrument}: risk_decision ignoré (signal_id mismatch)")
            return

        self.pending_signals.pop(instrument)
        signal_data = signal_item.get("payload", {})
        ts = signal_item.get("timestamp")
        if not isinstance(ts, datetime):
            self.expired_signals += 1
            self.log("WARN", f"signal {instrument} expiré après 90s sans réponse RiskAgent")
            return

        age = (datetime.now(timezone.utc) - ts).total_seconds()
        if age > self.signal_ttl_seconds:
            self.expired_signals += 1
            self.log("WARN", f"signal {instrument} expiré après 90s sans réponse RiskAgent")
            return
        
        if not approved:
            reason = risk_data.get("reason", "risque trop élevé")
            self.log("INFO", f"{instrument}: Rejeté — {reason}")
            return
        
        # DECISION FINALE : Trade approuvé
        direction = signal_data.get("direction", "?")
        confidence = float(signal_data.get("score", 0)) / 5.0
        risk_score = int(risk_data.get("risk_score", 0) or 0)

        if confidence < self.min_confidence:
            self.log("INFO", f"{instrument}: Rejeté — confiance {confidence:.1%} < {self.min_confidence:.0%}")
            return

        if risk_score < self.min_risk_score:
            self.log("INFO", f"{instrument}: Rejeté — risk_score {risk_score} < {self.min_risk_score}")
            return

        last_at = self.last_decision_at.get(instrument)
        now = datetime.now(timezone.utc)
        if last_at and (now - last_at).total_seconds() < self.instrument_cooldown_seconds:
            self.log("INFO", f"{instrument}: Cooldown actif, décision retardée")
            return
        
        # Décision finale
        decision = {
            "instrument": instrument,
            "direction": direction,
            "confidence": confidence,
            "sl_pips": risk_data.get("sl_pips", 30),
            "tp_pips": risk_data.get("tp_pips", 60),
            "signal_score": signal_data.get("score", 0),
            "signal_details": signal_data.get("details", {}) or {},
            "market_context": signal_data.get("market_context", {}),
            "risk_score": risk_score,
        }
        
        # Envoyer à ExecutionAgent pour exécution
        await self.send_message(
            "ExecutionAgent",
            "buy_signal" if direction == "BUY" else "sell_signal",
            decision
        )
        
        self.log("INFO", f"✅ {instrument}: DÉCISION {direction} (conf {decision['confidence']:.1%})")
        self.decisions_made += 1
        self.last_decision_at[instrument] = now
