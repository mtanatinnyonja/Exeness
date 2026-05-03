"""
Agent Décideur IA — Spécialisé XAUUSDm uniquement.
Reçoit signaux + évaluations risques, interroge le LLM local (Ollama) pour
une décision raisonnée, puis envoie l'ordre à ExecutionAgent.
Le LLM est obligatoire : sans réponse Ollama, aucune position n'est ouverte.
"""

import asyncio
import json
import re
import urllib.request
import urllib.error
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from agent_framework import Agent
import settings as cfg


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
        
        # === VALIDATION PAR LE LLM (obligatoire) ===
        llm_result = await self._ask_llm(instrument, direction, confidence, signal_data, risk_data)
        if not llm_result["approved"]:
            self.log("INFO", f"{instrument}: LLM refuse — {llm_result['reason']}")
            return

        # Décision finale validée par l'IA
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
            "llm_reasoning": llm_result.get("reasoning", ""),
        }
        
        # Envoyer à ExecutionAgent pour exécution
        await self.send_message(
            "ExecutionAgent",
            "buy_signal" if direction == "BUY" else "sell_signal",
            decision
        )
        
        self.log("INFO", f"✅ XAUUSDm: DÉCISION {direction} | conf {decision['confidence']:.1%} | SL={decision['sl_pips']}p TP={decision['tp_pips']}p | #{self.decisions_made + 1}")
        self.log("INFO", f"🧠 LLM reasoning: {llm_result.get('reasoning', '')[:120]}")
        self.decisions_made += 1
        self.last_decision_at[instrument] = now

    async def _ask_llm(
        self,
        instrument: str,
        direction: str,
        confidence: float,
        signal_data: Dict[str, Any],
        risk_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Interroge Ollama pour valider ou rejeter la décision de trade.
        
        Retourne {"approved": bool, "reason": str, "reasoning": str}.
        Si Ollama est injoignable, retourne approved=False.
        """
        score = signal_data.get("score", 0)
        spread = signal_data.get("spread", 0)
        regime = signal_data.get("market_context", {}).get("regime", "?") if isinstance(signal_data.get("market_context"), dict) else "?"
        session = signal_data.get("session", "?")
        if isinstance(session, dict):
            session = session.get("label", "?")
        sl_pips = risk_data.get("sl_pips", 30)
        tp_pips = risk_data.get("tp_pips", 60)
        risk_score = risk_data.get("risk_score", 0)
        details = signal_data.get("details", {}) or {}

        prompt = (
            f"Tu es un agent IA spécialisé sur XAUUSDm (or/USD). "
            f"Décide si ce signal de trading doit être exécuté.\n\n"
            f"SIGNAL:\n"
            f"- Direction: {direction}\n"
            f"- Score technique: {score}/5\n"
            f"- Confiance calculée: {confidence:.0%}\n"
            f"- Spread actuel: {spread:.1f} pips\n"
            f"- Régime marché: {regime}\n"
            f"- Session: {session}\n"
            f"- SL: {sl_pips} pips | TP: {tp_pips} pips (ratio 1:{tp_pips/sl_pips:.1f})\n"
            f"- Score risque: {risk_score}/5\n"
            f"- Détails indicateurs: {json.dumps(details, ensure_ascii=False)[:300]}\n\n"
            f"RÈGLES:\n"
            f"- Capital $100, objectif +$5/jour, stop -$10/jour\n"
            f"- Spread gold max acceptable: 6 pips\n"
            f"- Ne trader que si le signal est clair et le contexte favorable\n"
            f"- En cas de doute, répondre NON\n\n"
            f"Réponds UNIQUEMENT avec ce format JSON (sans markdown):\n"
            f'{{\"decision\": \"OUI\" ou \"NON\", \"raison\": \"explication courte\"}}'
        )

        payload = json.dumps({
            "model": cfg.LOCAL_LLM_MODEL,
            "prompt": prompt,
            "stream": False,
            "temperature": cfg.LLM_TEMPERATURE,
            "options": {"num_predict": 120},
        }).encode("utf-8")

        endpoint = cfg.LOCAL_LLM_ENDPOINT
        try:
            req = urllib.request.Request(
                endpoint,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=cfg.LOCAL_LLM_TIMEOUT) as resp:
                raw = resp.read().decode("utf-8")
            response_data = json.loads(raw)
            text = response_data.get("response", "").strip()
        except (urllib.error.URLError, OSError) as exc:
            self.log("ERROR", f"LLM injoignable ({endpoint}): {exc} — trade annulé")
            return {"approved": False, "reason": f"Ollama injoignable: {exc}", "reasoning": ""}
        except Exception as exc:
            self.log("ERROR", f"LLM erreur inattendue: {exc} — trade annulé")
            return {"approved": False, "reason": str(exc), "reasoning": ""}

        # Parser la réponse JSON du LLM
        try:
            # Extraire le JSON même si le LLM ajoute du texte autour
            match = re.search(r'\{[^{}]+\}', text, re.DOTALL)
            if match:
                parsed = json.loads(match.group())
            else:
                parsed = json.loads(text)
            decision_str = str(parsed.get("decision", "NON")).strip().upper()
            raison = str(parsed.get("raison", text[:120]))
            approved = decision_str in ("OUI", "YES", "TRUE", "1")
            return {"approved": approved, "reason": raison, "reasoning": text[:300]}
        except (json.JSONDecodeError, KeyError):
            # Fallback: cherche OUI/NON dans le texte brut
            upper_text = text.upper()
            if "OUI" in upper_text or '"YES"' in upper_text:
                return {"approved": True, "reason": "LLM approuve (parsing souple)", "reasoning": text[:300]}
            return {"approved": False, "reason": f"LLM répond NON ou illisible: {text[:80]}", "reasoning": text[:300]}
