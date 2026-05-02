"""
Agent Analyste — Lit le marché, identifie les setups, envoie des signaux.
Tourne en boucle autonome, indépendant de tout orchestrateur.
"""

import asyncio
import time
from typing import Dict, Any, Optional, List
from agent_framework import Agent, get_message_bus
from mt5_bridge import build_broker
from signal_engine import calculate_signal_score
from smart_strategies import build_strategies_context, get_session_score
from market_context import analyze_market_context
from learning_store import AgentMemory
from settings import PRIMARY_TIMEFRAME, CONFIRM_TIMEFRAME, INSTRUMENTS


class AnalystAgent(Agent):
    """Analyste autonome — Lit marché en continu, publie signaux."""
    
    def __init__(self, instruments: Optional[List[str]] = None):
        super().__init__("AnalystAgent")
        self.broker = build_broker()
        self.memory = AgentMemory()
        self.instruments = instruments or INSTRUMENTS or ["EURUSDm", "XAUUSDm", "BTCUSDm"]
        self.cycle_count = 0
        self.last_analysis = {}  # instrument -> timestamp dernière analyse
    
    async def on_startup(self):
        """Initialisation."""
        self.log("INFO", f"Démarré. Instruments: {self.instruments}")
        await self.bus.subscribe(self.name, ["start_analysis", "market_tick"])
    
    async def run(self):
        """Boucle autonome — analyse le marché en continu."""
        while self.running:
            self.cycle_count += 1
            
            # Analyser chaque instrument en rotation
            for instrument in self.instruments:
                await self._analyze_instrument(instrument)
                await asyncio.sleep(0.1)  # Anti-spam
            
            # Attendre 30s avant prochain cycle
            await asyncio.sleep(30)
    
    async def _analyze_instrument(self, instrument: str):
        """Analyse un instrument et envoie un signal."""
        try:
            # Récupérer les données
            candles_h1 = self.broker.get_candles(instrument, PRIMARY_TIMEFRAME, 100)
            if len(candles_h1) < 20:
                return
            
            candles_m15 = self.broker.get_candles(instrument, CONFIRM_TIMEFRAME, 60)
            
            # Calcul du signal
            signal = calculate_signal_score(candles_h1, instrument)
            signal_confirm = None
            if len(candles_m15) >= 20:
                signal_confirm = calculate_signal_score(candles_m15, instrument)
            
            # Contexte marché
            market_context = analyze_market_context(candles_h1, instrument)
            session = get_session_score(instrument)
            
            # Strategies
            strategies = build_strategies_context(
                instrument, candles_h1, [], [],
                signal_direction=signal.get("direction"),
                signal_score=signal.get("score", 0),
                open_positions=[]
            )
            
            # Envoyer le signal à tous les autres agents
            if signal.get("direction") in ("BUY", "SELL"):
                await self.send_message(
                    recipient="*",  # Broadcast
                    event_type="signal",
                    payload={
                        "instrument": instrument,
                        "direction": signal["direction"],
                        "score": signal["score"],
                        "details": signal.get("details", {}),
                        "market_context": market_context,
                        "session": session,
                        "strategies": strategies,
                        "signal_confirm": signal_confirm,
                        "spread": self.broker.get_spread_pips(instrument),
                    }
                )
                self.log("INFO", f"{instrument}: Signal {signal['direction']} (force {signal['score']}/5)")
            
            self.last_analysis[instrument] = time.time()
        
        except Exception as e:
            self.log("ERROR", f"{instrument}: {str(e)[:100]}")
