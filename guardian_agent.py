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
        await self.bus.subscribe(self.name, ["trade_opened", "position_alert"])
    
    async def run(self):
        """Boucle autonome — surveille positions en continu."""
        while self.running:
            await self._check_all_positions()
            self.check_count += 1
            self.write_heartbeat({"check_count": self.check_count})
            await asyncio.sleep(5)  # Check toutes les 5s
    
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
        direction = position.get("direction", "?")
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
            atr = float(signal.get("details", {}).get("atr", 0) or 0)
            
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

            # 2. Perte trop grande → CLOSE (SL manuel de sécurité si MT5 échoue)
            elif unrealized_pnl < -10.0:
                action = "CLOSE"
                reason = f"perte urgence ${unrealized_pnl:.2f}"

            # 3. Breakeven : si profit >= 50% du TP, déplacer SL à l'entrée
            elif (not state["breakeven_set"] and entry > 0 and sl_price > 0
                    and tp_price > 0 and current > 0 and atr > 0):
                tp_distance = abs(tp_price - entry)
                current_distance = abs(current - entry)
                if tp_distance > 0 and current_distance >= tp_distance * 0.5:
                    # Déplacer SL au breakeven + 1 ATR de marge
                    margin = atr * 0.3
                    if direction == "BUY":
                        new_sl = entry + margin
                        if new_sl > sl_price:  # seulement si ça améliore le SL
                            action = "TIGHTEN"
                            reason = "breakeven: SL déplacé à l'entrée"
                            state["breakeven_set"] = True
                    elif direction == "SELL":
                        new_sl = entry - margin
                        if new_sl < sl_price:
                            action = "TIGHTEN"
                            reason = "breakeven: SL déplacé à l'entrée"
                            state["breakeven_set"] = True

            # 4. Trailing stop : si profit > peak, serrer le SL
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
                    "guardian_action",
                    {"instrument": instrument, "action": "CLOSE", "reason": reason, "unrealized_pnl": unrealized_pnl}
                )
            elif action == "TIGHTEN" and new_sl is not None:
                await self.send_message(
                    "ExecutionAgent",
                    "guardian_action",
                    {"instrument": instrument, "action": "TIGHTEN", "reason": reason, "new_sl": new_sl}
                )
        
        except Exception as e:
            self.log("ERROR", f"{instrument}: {str(e)[:100]}")

