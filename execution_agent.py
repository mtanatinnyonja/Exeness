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
from signal_engine import calculate_atr
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
        # Le décideur impose déjà 120s de cooldown par instrument.
        # La fenêtre de confirmation doit donc rester au-dessus de ce délai.
        self.confirmation_window_seconds = 180
        self._signal_confirmations = {}
    
    async def on_startup(self):
        """Initialisation."""
        self.log("INFO", "Démarré. En attente de décisions...")
        await self.bus.subscribe(self.name, ["buy_signal", "sell_signal", "close_position"])
    
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
            elif message:
                self.log("WARN", f"Message inconnu ignoré: {message.event_type}")
            
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
                self.telegram.send_trade_alert(
                    trade_data={
                        "instrument": instrument,
                        "direction": direction,
                        "volume": volume,
                        "entry": float(order.get("entry_price", 0)),
                        "sl": float(order.get("stop_loss", 0) or sl_pips),
                        "tp": float(order.get("take_profit", 0) or tp_pips),
                        "sl_pips": int(sl_pips),
                        "tp_pips": int(tp_pips),
                        "signal_score": int(decision.get("signal_score", 0) or 0),
                    },
                    signal_details=decision.get("signal_details", {}) or {},
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

    async def _update_trailing_stop(self, position: Dict[str, Any]):
        """Met à jour le trailing stop basé ATR H1 (sans modifier le TP)."""
        instrument = str(position.get("instrument", "?"))
        direction = str(position.get("direction", "")).upper()
        ticket = position.get("ticket")

        if direction not in ("BUY", "SELL"):
            return
        if ticket in (None, "", 0):
            return

        current_price = float(
            position.get("price_current", position.get("current_price", 0.0)) or 0.0
        )
        sl_current = float(position.get("sl", position.get("stop_loss", 0.0)) or 0.0)
        entry_price = float(position.get("avg_price", position.get("entry_price", 0.0)) or 0.0)
        if current_price <= 0 or entry_price <= 0:
            return

        try:
            candles_h1 = self.broker.get_candles(instrument, "H1", 20)
            if len(candles_h1) < 20:
                return

            atr = float(calculate_atr(candles_h1) or 0.0)
            if atr <= 0:
                return

            pip_size = float(self.broker._pip_size(instrument) or 0.0001)
            if pip_size <= 0:
                return

            if direction == "BUY":
                profit_pips = (current_price - entry_price) / pip_size
            else:
                profit_pips = (entry_price - current_price) / pip_size

            atr_pips = atr / pip_size
            trigger_pips = atr_pips * 1.5
            if profit_pips < trigger_pips:
                return

            if direction == "BUY":
                new_sl = current_price - (0.8 * atr)
                if sl_current > 0 and new_sl <= sl_current:
                    return
            else:
                new_sl = current_price + (0.8 * atr)
                if sl_current > 0 and new_sl >= sl_current:
                    return

            changed = self.broker.modify_sl(int(ticket), float(new_sl))
            if changed:
                self.log(
                    "INFO",
                    f"Trailing stop mis à jour : {instrument} SL {sl_current:.5f} -> {new_sl:.5f}",
                )
        except Exception as e:
            self.log("WARN", f"{instrument}: trailing stop indisponible: {str(e)[:100]}")
    
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


