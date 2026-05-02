"""
Agent Exécution — Reçoit les décisions approuvées et exécute les ordres.
Autonome, gère l'exécution sans dépendre d'un orchestrateur.
"""

import asyncio
from typing import Dict, Any
from agent_framework import Agent
from mt5_bridge import build_broker
from learning_store import AgentMemory
from circuit_breaker import CircuitBreaker
from audit_logger import get_audit_logger
from settings import MAX_RISK_PER_TRADE, MAX_OPEN_POSITIONS


class ExecutionAgent(Agent):
    """Exécuteur autonome — Reçoit décisions, exécute ordres, gère positions."""
    
    def __init__(self):
        super().__init__("ExecutionAgent")
        self.broker = build_broker()
        self.memory = AgentMemory()
        self.circuit_breaker = CircuitBreaker()
        self.audit = get_audit_logger()
        self.executed_trades = 0
    
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
            
            # Surveiller les positions existantes
            await self._check_positions()
            self.write_heartbeat()
            await asyncio.sleep(1)
    
    async def _execute_trade(self, decision: Dict[str, Any]):
        """Exécute un trade approuvé."""
        instrument = decision.get("instrument", "?")
        direction = decision.get("direction", "?")
        
        try:
            # Vérifier les limites
            open_positions = self.broker.get_open_positions()
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
        
        except Exception as e:
            self.log("ERROR", f"{instrument}: {str(e)[:100]}")
    
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
        except Exception as e:
            self.log("ERROR", f"{instrument}: Impossible fermer: {str(e)[:100]}")
