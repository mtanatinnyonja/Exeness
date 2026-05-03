"""
Agent Gardien — Surveille les positions ouvertes en continu.
Autonome, décide de HOLD/CLOSE/TIGHTEN sur ses propres observations.
"""

import asyncio
from typing import Dict, List
from agent_framework import Agent
from mt5_bridge import build_broker
from signal_engine import calculate_signal_score, calculate_atr
from settings import PRIMARY_TIMEFRAME


class GuardianAgent(Agent):
    """Gardien autonome — Surveille positions, prend décisions HOLD/CLOSE/TIGHTEN."""
    
    def __init__(self):
        super().__init__("GuardianAgent")
        self.broker = build_broker()
        self.check_count = 0
        # Trailing state: instrument → {"breakeven_set": bool, "peak_pnl": float}
        self._position_state: Dict[str, Dict] = {}
    
    async def on_startup(self):
        """Initialisation."""
        self.log("INFO", "Démarré. Surveillance en continu...")
        await self.bus.subscribe(self.name, [])
    
    async def run(self):
        """Boucle autonome — surveille positions en continu."""
        while self.running:
            await self._check_all_positions()
            self.check_count += 1
            self.write_heartbeat({"check_count": self.check_count})
            await asyncio.sleep(5)  # Check toutes les 5s

    def _modify_position_safe(self, instrument: str, stop_loss: float = None, take_profit: float = None) -> bool:
        """Wrapper sûr: modifie une position si le broker expose modify_position."""
        if not hasattr(self.broker, "modify_position"):
            self.log("WARN", "Broker.modify_position indisponible, trailing ignoré")
            return False
        try:
            return bool(self.broker.modify_position(instrument, stop_loss=stop_loss, take_profit=take_profit))
        except Exception as e:
            self.log("WARN", f"modify_position échoué sur {instrument}: {e}")
            return False
    
    async def _check_all_positions(self):
        """Surveille toutes les positions ouvertes."""
        try:
            positions = self.broker.get_open_positions()
            if not positions:
                self._position_state.clear()
                return
            
            open_instruments = {p.get("instrument") for p in positions}
            # Nettoyer état des positions fermées
            for inst in list(self._position_state.keys()):
                if inst not in open_instruments:
                    del self._position_state[inst]

            for position in positions:
                await self._monitor_position(position)
        
        except Exception as e:
            self.log("ERROR", f"Check positions: {str(e)[:100]}")
    
    async def _monitor_position(self, position: Dict):
        """Surveille une position et décide action."""
        instrument = position.get("instrument", "?")
        direction = str(position.get("direction", "?")).upper()
        entry = float(position.get("entry_price", 0))
        current = float(position.get("current_price", 0))
        unrealized_pnl = float(position.get("unrealized_pnl", 0))
        sl_price = float(position.get("stop_loss", 0))
        tp_price = float(position.get("take_profit", 0))
        
        # Init état trailing si nouveau trade
        if instrument not in self._position_state:
            self._position_state[instrument] = {"breakeven_set": False, "peak_pnl": 0.0}
        state = self._position_state[instrument]

        try:
            # Récupérer candles pour signal + ATR
            candles = self.broker.get_candles(instrument, PRIMARY_TIMEFRAME, 50)
            if len(candles) < 20:
                return
            
            signal = calculate_signal_score(candles, instrument)
            signal_direction = signal.get("direction", "WAIT")
            signal_score = signal.get("score", 0)
            atr = float(calculate_atr(candles) or 0)
            pip_size = float(self.broker._pip_size(instrument) or 0.0001)
            atr_pips = (atr / pip_size) if pip_size > 0 and atr > 0 else 0.0
            if atr_pips <= 0:
                return

            # Mouvement latent en pips, signé dans le sens de la position
            if direction == "BUY":
                move_pips = (current - entry) / pip_size if entry > 0 and current > 0 else 0.0
            else:
                move_pips = (entry - current) / pip_size if entry > 0 and current > 0 else 0.0

            loss_threshold_value = -(atr_pips * pip_size * 2.0)
            gain_threshold_value = (atr_pips * pip_size * 4.0)
            trail_threshold_pips = atr_pips * 2.0
            
            action = "HOLD"
            reason = "position stable"
            new_sl = None

            # 1. Reversal fort → CLOSE immédiat
            if direction == "BUY" and signal_direction == "SELL" and signal_score >= 3:
                action = "CLOSE"
                reason = f"reversal SELL détecté ({signal_score}/5)"
            elif direction == "SELL" and signal_direction == "BUY" and signal_score >= 3:
                action = "CLOSE"
                reason = f"reversal BUY détecté ({signal_score}/5)"

            # 2. Seuil perte relatif ATR (valeur) → CLOSE
            elif unrealized_pnl < loss_threshold_value:
                action = "CLOSE"
                reason = f"perte ATR: ${unrealized_pnl:.2f} < ${loss_threshold_value:.2f}"

            # 3. Seuil gain relatif ATR (valeur) → CLOSE part prudence Guardian
            elif unrealized_pnl > gain_threshold_value:
                action = "CLOSE"
                reason = f"gain ATR: ${unrealized_pnl:.2f} > ${gain_threshold_value:.2f}"

            # 4. Trailing break-even: profit > ATR*2.0, resserrer le SL à l'entrée
            elif (not state["breakeven_set"] and entry > 0 and move_pips >= trail_threshold_pips):
                new_sl = entry
                can_improve = (direction == "BUY" and (sl_price <= 0 or new_sl > sl_price)) or (
                    direction == "SELL" and (sl_price <= 0 or new_sl < sl_price)
                )
                if can_improve and self._modify_position_safe(instrument, stop_loss=new_sl):
                    state["breakeven_set"] = True
                    action = "TIGHTEN"
                    reason = f"break-even activé (> {trail_threshold_pips:.1f}p)"

            # 5. Trailing stop : si profit > peak, close sur fort repli
            if action == "HOLD" and state["breakeven_set"] and atr > 0 and current > 0:
                state["peak_pnl"] = max(state["peak_pnl"], unrealized_pnl)
                # Si on est retombé de 40% depuis le peak → CLOSE pour protéger gains
                if unrealized_pnl > 0 and state["peak_pnl"] > 2.0:
                    drawdown_ratio = (state["peak_pnl"] - unrealized_pnl) / state["peak_pnl"]
                    if drawdown_ratio > 0.40:
                        action = "CLOSE"
                        reason = f"trailing stop: repli {drawdown_ratio:.0%} depuis peak ${state['peak_pnl']:.2f}"

            # Log
            emoji = {"HOLD": "✅", "CLOSE": "🔴", "TIGHTEN": "🔄"}.get(action, "?")
            self.log("INFO", f"{emoji} {instrument} {direction}: {action} ({reason}) | P&L: ${unrealized_pnl:+.2f}")
            
            # Envoyer l'action
            if action == "CLOSE":
                await self.send_message(
                    "ExecutionAgent",
                    "close_position",
                    {"instrument": instrument, "reason": reason, "unrealized_pnl": unrealized_pnl}
                )
        
        except Exception as e:
            self.log("ERROR", f"{instrument}: {str(e)[:100]}")

