"""
Agent Exécution — Reçoit les décisions approuvées et exécute les ordres.
Autonome, gère l'exécution sans dépendre d'un orchestrateur.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Dict, Any
from agent_framework import Agent
from mt5_bridge import build_broker
from learning_store import AgentMemory
from circuit_breaker import CircuitBreaker
from audit_logger import get_audit_logger
from telegram_notifier import TelegramNotifier
from settings import MAX_RISK_PER_TRADE, MAX_OPEN_POSITIONS


class ExecutionAgent(Agent):
    """Exécuteur autonome — Reçoit décisions, exécute ordres, gère positions."""
    
    def __init__(self):
        super().__init__("ExecutionAgent")
        self.broker = build_broker()
        self.memory = AgentMemory()
        self.circuit_breaker = CircuitBreaker()
        self.audit = get_audit_logger()
        self.telegram = TelegramNotifier()
        self.executed_trades = 0
        self.execution_block_until = None
        self.execution_block_reason = ""
        self._last_block_log_ts = None
        self.started_at = datetime.now(timezone.utc)
        self.startup_warmup_seconds = 120
        self.min_confidence = 0.55
        self.required_confirmations = 2
        self.confirmation_window_seconds = 90
        self._signal_confirmations = {}
    
    async def on_startup(self):
        """Initialisation."""
        self.log("INFO", "Démarré. En attente de décisions...")
        await self.bus.subscribe(self.name, ["buy_signal", "sell_signal", "close_position", "guardian_action"])
    
    async def run(self):
        """Boucle autonome — exécute les ordres approuvés."""
        while self.running:
            # Check circuit breaker
            if not self.circuit_breaker.can_trade():
                cb_status = self.circuit_breaker.get_status()
                self.log("WARN", f"Circuit breaker actif: {cb_status['reason']}")
                await asyncio.sleep(10)
                continue
            
            # Attendre un message d'exécution
            message = await self.wait_for_message(timeout=2.0)
            
            if message and message.event_type in ("buy_signal", "sell_signal"):
                await self._execute_trade(message.payload)
            elif message and message.event_type == "close_position":
                await self._close_position(message.payload)
            elif message and message.event_type == "guardian_action":
                action = message.payload.get("action", "HOLD")
                if action == "CLOSE":
                    await self._close_position(message.payload)
                elif action == "TIGHTEN":
                    await self._tighten_sl(message.payload)
            
            # Surveiller les positions existantes
            await self._check_positions()
            self.write_heartbeat()
            await asyncio.sleep(1)
    
    async def _execute_trade(self, decision: Dict[str, Any]):
        """Exécute un trade approuvé."""
        instrument = decision.get("instrument", "?")
        direction = decision.get("direction", "?")
        confidence = float(decision.get("confidence", 0.0) or 0.0)

        # Warmup: laisser le système observer le marché avant toute première exécution.
        uptime_seconds = int((datetime.now(timezone.utc) - self.started_at).total_seconds())
        if uptime_seconds < self.startup_warmup_seconds:
            remaining = self.startup_warmup_seconds - uptime_seconds
            self.log("INFO", f"{instrument}: Warmup actif ({remaining}s restants), exécution différée")
            return

        # Confidence gate: évite les décisions trop faibles.
        if confidence < self.min_confidence:
            self.log(
                "INFO",
                f"{instrument}: Ignoré (confiance {confidence:.1%} < seuil {self.min_confidence:.0%})"
            )
            return

        # Confirmation gate: exige deux validations cohérentes dans une fenêtre courte.
        key = f"{str(instrument).upper()}|{str(direction).upper()}"
        now = datetime.now(timezone.utc)
        history = self._signal_confirmations.get(key, [])
        history = [ts for ts in history if (now - ts).total_seconds() <= self.confirmation_window_seconds]
        history.append(now)
        self._signal_confirmations[key] = history
        if len(history) < self.required_confirmations:
            self.log(
                "INFO",
                f"{instrument}: Confirmation {len(history)}/{self.required_confirmations} ({direction}), attente validation"
            )
            return
        # Reset after passing gate so the next entry must reconfirm.
        self._signal_confirmations[key] = []

        if self.execution_block_until and datetime.now(timezone.utc) < self.execution_block_until:
            if not self._last_block_log_ts or (datetime.now(timezone.utc) - self._last_block_log_ts).total_seconds() >= 30:
                wait_s = int((self.execution_block_until - datetime.now(timezone.utc)).total_seconds())
                self.log("WARN", f"Exécution temporairement bloquée ({wait_s}s): {self.execution_block_reason}")
                self._last_block_log_ts = datetime.now(timezone.utc)
            return
        
        try:
            # Vérifier les limites
            open_positions = self.broker.get_open_positions()
            # Hard guard: single-position mode to prevent stacking entries.
            if len(open_positions) >= 1:
                existing = open_positions[0]
                self.log(
                    "INFO",
                    f"{instrument}: Entrée ignorée (position déjà ouverte sur {existing.get('instrument', '?')})"
                )
                return

            # Extra guard: never open a second position on the same symbol.
            if any(str(p.get("instrument", "")).upper() == str(instrument).upper() for p in open_positions):
                self.log("INFO", f"{instrument}: Entrée ignorée (position existante sur la paire)")
                return

            if len(open_positions) >= MAX_OPEN_POSITIONS:
                self.log("WARN", f"{instrument}: Max positions atteint")
                return
            
            # Récupérer l'account
            account = self.broker.get_account_summary()
            balance = account.get("balance", 1000)
            
            # Calcul du risque et volume
            sl_pips = decision.get("sl_pips", 30)
            tp_pips = decision.get("tp_pips", 60)
            risk_usd = balance * MAX_RISK_PER_TRADE
            
            volume = self.broker.calculate_volume(instrument, risk_usd, sl_pips)
            
            # Placer l'ordre
            order = self.broker.place_market_order(
                instrument=instrument,
                direction=direction,
                volume=volume,
                stop_loss_pips=sl_pips,
                take_profit_pips=tp_pips,
                comment=f"AUTO|{direction}"
            )
            
            if order:
                # Enregistrer
                trade_id = self.memory.add_trade({
                    "instrument": instrument,
                    "direction": direction,
                    "volume": volume,
                    "entry_price": order.get("entry_price", 0),
                    "stop_loss": order.get("stop_loss", 0),
                    "take_profit": order.get("take_profit", 0),
                    "broker_id": order.get("broker_id"),
                    "sl_pips": sl_pips,
                    "tp_pips": tp_pips,
                    "risk_usd": risk_usd,
                    "status": "open"
                })
                
                # Log audit
                self.audit.log_execution(
                    instrument, direction, volume,
                    order.get("entry_price", 0),
                    order.get("stop_loss", 0),
                    order.get("take_profit", 0),
                    order.get("broker_id", "")
                )
                
                # Notifier
                await self.send_message(
                    "*",
                    "trade_opened",
                    {
                        "trade_id": trade_id,
                        "instrument": instrument,
                        "direction": direction,
                        "entry": order.get("entry_price", 0),
                    }
                )
                
                self.log("INFO", f"{instrument}: {direction} executé | vol={volume} | SL={sl_pips}p TP={tp_pips}p")
                self.executed_trades += 1
                self.telegram.notify_trade_opened(
                    instrument=instrument,
                    direction=direction,
                    volume=volume,
                    entry_price=float(order.get("entry_price", 0)),
                    sl_pips=int(sl_pips),
                    tp_pips=int(tp_pips),
                    confidence=confidence,
                    risk_usd=risk_usd,
                )
        
        except Exception as e:
            err = str(e)
            if "10027" in err:
                self.execution_block_until = datetime.now(timezone.utc) + timedelta(minutes=2)
                self.execution_block_reason = "MT5 auto-trading désactivé côté terminal (retcode 10027)"
                self.log("ERROR", f"{instrument}: {err[:140]} | Active Algo Trading dans MT5 puis réessaie.")
                return
            if "10024" in err:
                self.execution_block_until = datetime.now(timezone.utc) + timedelta(seconds=30)
                self.execution_block_reason = "Trop de requêtes MT5 (retcode 10024)"
                self.log("WARN", f"{instrument}: {err[:120]} | Pause 30s anti-spam")
                return
            self.log("ERROR", f"{instrument}: {err[:100]}")
    
    async def _check_positions(self):
        """Vérifie les positions ouvertes."""
        try:
            positions = self.broker.get_open_positions()
            for pos in positions:
                instrument = pos.get("instrument", "?")
                pnl = float(pos.get("unrealized_pnl", 0))
                
                # Log pour monitoring
                if pnl < -5.0:
                    self.log("WARN", f"{instrument}: Perte ${pnl:.2f}")
        except Exception:
            pass
    
    async def _close_position(self, data: Dict[str, Any]):
        """Ferme une position."""
        instrument = data.get("instrument", "?")
        reason = data.get("reason", "unknown")
        
        try:
            pnl = self.broker.close_position(instrument)
            self.log("INFO", f"{instrument}: Fermé ({reason}) | P&L: ${pnl:.2f}")
            self.telegram.notify_trade_closed(instrument, "", pnl, reason=reason)
        except Exception as e:
            self.log("ERROR", f"{instrument}: Impossible fermer: {str(e)[:100]}")

    async def _tighten_sl(self, data: Dict[str, Any]):
        """Resserre le SL sur une position (breakeven ou trailing)."""
        instrument = data.get("instrument", "?")
        new_sl = data.get("new_sl")
        if not new_sl:
            return
        try:
            result = self.broker.modify_sl(instrument, new_sl)
            if result:
                self.log("INFO", f"{instrument}: SL déplacé → {new_sl:.5f} (trailing/breakeven)")
        except Exception as e:
            self.log("ERROR", f"{instrument}: Modify SL: {str(e)[:80]}")
