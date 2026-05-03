"""
Agent Décideur — Spécialisé XAUUSDm uniquement.
Reçoit signaux + évaluations risques et prend la décision finale d'exécution.
"""

import asyncio
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from agent_framework import Agent


class DecisionAgent(Agent):
    """Décideur XAUUSDm — Synthètise signaux et risques pour décision finale."""
    
    def __init__(self):
        super().__init__("DecisionAgent")
        self.pending_signals: Dict[str, Dict] = {}
        self.decisions_made = 0
        self.expired_signals = 0
        self.min_confidence = 0.60         # 3/5 minimum
        self.min_risk_score = 3             # Risk score minimum XAU
        self.signal_ttl_seconds = 90
        self.cleanup_interval_seconds = 30
        self._last_cleanup_at = datetime.now(timezone.utc)
        self.instrument_cooldown_seconds = 120  # 2 min entre trades XAU
        self.last_decision_at: Dict[str, datetime] = {}
    
    async def on_startup(self):
        """Initialisation."""
        self.log("INFO", "Démarré. En attente de signaux et approvals...")
        await self.bus.subscribe(self.name, ["signal", "risk_decision"])
    
    async def run(self):
        """Boucle autonome — synthètise et décide (XAUUSDm only)."""
        while self.running:
            now = datetime.now(timezone.utc)
            if (now - self._last_cleanup_at).total_seconds() >= self.cleanup_interval_seconds:
                self._cleanup_expired_signals()
                self._last_cleanup_at = now

            message = await self.wait_for_message(timeout=1.0)
            
            if message and message.event_type == "signal":
                instrument = message.payload.get("instrument", "?")
                self.pending_signals[instrument] = {
                    "payload": message.payload,
                    "timestamp": datetime.now(timezone.utc),
                    "signal_id": message.payload.get("signal_id", ""),
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
        """Traite une décision de risque XAU et décide si on trade."""
        instrument = risk_data.get("instrument", "?")

        # Ignorer tout signal non-XAU
        if str(instrument).upper() != "XAUUSDM":
            return
        approved = risk_data.get("approved", False)
        risk_signal_id = risk_data.get("signal_id", "")
        
        pending = self.pending_signals.get(instrument)
        if not pending:
            return

        if risk_signal_id and pending["signal_id"] and risk_signal_id != pending["signal_id"]:
            self.log("WARN", f"{instrument}: signal_id mismatch, signal ignoré")
            return

        signal_item = self.pending_signals.pop(instrument)
        signal_data = signal_item["payload"]
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
        confidence = min(float(signal_data.get("score", 0) or 0.0), 5.0) / 5.0
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
        
        self.log("INFO", f"✅ XAUUSDm: DÉCISION {direction} | conf {decision['confidence']:.1%} | SL={decision['sl_pips']}p TP={decision['tp_pips']}p | #{self.decisions_made + 1}")
        self.decisions_made += 1
        self.last_decision_at[instrument] = now
