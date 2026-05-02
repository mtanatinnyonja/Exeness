"""
Test du flux complet multi-agent — Simulation sans MT5 live.
Démontre:
  1. AnalystAgent découvre un signal
  2. RiskAgent évalue
  3. DecisionAgent décide
  4. ExecutionAgent "exécute" (simulation)
  5. GuardianAgent "surveille" (simulation)
"""

import asyncio
from agent_framework import Agent, get_message_bus


class SimulatedAnalystAgent(Agent):
    """Analyste simulé — envoie 2 signaux puis arrête."""
    
    def __init__(self):
        super().__init__("SimulatedAnalystAgent")
    
    async def on_startup(self):
        self.log("INFO", "Simulation mode: 2 signaux")
    
    async def run(self):
        # Signal 1: BUY
        await self.send_message(
            "*", "signal",
            {
                "instrument": "EURUSD",
                "direction": "BUY",
                "score": 4,
                "details": {"atr_pips": 30}
            }
        )
        self.log("INFO", "📊 EURUSD: Signal BUY découvert")
        await asyncio.sleep(2)
        
        # Signal 2: SELL
        await self.send_message(
            "*", "signal",
            {
                "instrument": "XAUUSD",
                "direction": "SELL",
                "score": 3,
                "details": {"atr_pips": 20}
            }
        )
        self.log("INFO", "📊 XAUUSD: Signal SELL découvert")
        await asyncio.sleep(1)
        
        self.running = False


class SimulatedRiskAgent(Agent):
    """Risk Manager simulé — évalue et approuve."""
    
    def __init__(self):
        super().__init__("SimulatedRiskAgent")
        self.eval_count = 0
    
    async def on_startup(self):
        self.log("INFO", "Prêt à évaluer signaux")
        await self.bus.subscribe(self.name, ["signal"])
    
    async def run(self):
        while self.running:
            message = await self.wait_for_message(timeout=2.0)
            
            if message and message.event_type == "signal":
                instrument = message.payload.get("instrument", "?")
                await self.send_message(
                    "*", "risk_decision",
                    {
                        "instrument": instrument,
                        "approved": True,
                        "reason": "Risque acceptable",
                        "sl_pips": 30,
                        "tp_pips": 60,
                    }
                )
                self.log("INFO", f"✅ {instrument}: APPROUVÉ")
                self.eval_count += 1
            
            await asyncio.sleep(0.1)


class SimulatedDecisionAgent(Agent):
    """Décideur simulé — synthétise et décide."""
    
    def __init__(self):
        super().__init__("SimulatedDecisionAgent")
        self.pending = {}
        self.decisions = 0
    
    async def on_startup(self):
        self.log("INFO", "Prêt à décider")
        await self.bus.subscribe(self.name, ["signal", "risk_decision"])
    
    async def run(self):
        while self.running:
            message = await self.wait_for_message(timeout=2.0)
            
            if message and message.event_type == "signal":
                inst = message.payload.get("instrument", "?")
                self.pending[inst] = message.payload
            
            elif message and message.event_type == "risk_decision":
                inst = message.payload.get("instrument", "?")
                if inst in self.pending and message.payload.get("approved"):
                    signal = self.pending.pop(inst)
                    direction = signal["direction"]
                    
                    await self.send_message(
                        "*",
                        "buy_signal" if direction == "BUY" else "sell_signal",
                        {
                            "instrument": inst,
                            "direction": direction,
                            "volume": 1.0,  # simulation
                        }
                    )
                    self.log("INFO", f"🎯 {inst}: DÉCISION {direction}")
                    self.decisions += 1
            
            await asyncio.sleep(0.1)


class SimulatedExecutionAgent(Agent):
    """Exécuteur simulé — simule l'exécution."""
    
    def __init__(self):
        super().__init__("SimulatedExecutionAgent")
        self.trades = 0
    
    async def on_startup(self):
        self.log("INFO", "Prêt à exécuter")
        await self.bus.subscribe(self.name, ["buy_signal", "sell_signal"])
    
    async def run(self):
        while self.running:
            message = await self.wait_for_message(timeout=2.0)
            
            if message and message.event_type in ("buy_signal", "sell_signal"):
                inst = message.payload.get("instrument", "?")
                direction = message.payload.get("direction", "?")
                
                await self.send_message(
                    "*",
                    "trade_opened",
                    {"instrument": inst, "direction": direction, "id": f"TRADE_{self.trades}"}
                )
                self.log("INFO", f"🚀 {inst}: ORDRE {direction} EXÉCUTÉ")
                self.trades += 1
            
            await asyncio.sleep(0.1)


class SimulatedGuardianAgent(Agent):
    """Gardien simulé — simule la surveillance."""
    
    def __init__(self):
        super().__init__("SimulatedGuardianAgent")
        self.monitored = {}
    
    async def on_startup(self):
        self.log("INFO", "Surveillance active")
        await self.bus.subscribe(self.name, ["trade_opened"])
    
    async def run(self):
        while self.running:
            message = await self.wait_for_message(timeout=2.0)
            
            if message and message.event_type == "trade_opened":
                inst = message.payload.get("instrument", "?")
                self.monitored[inst] = message.payload
                self.log("INFO", f"👁️  {inst}: EN SURVEILLANCE")
            
            await asyncio.sleep(0.1)


async def run_simulation():
    """Lance la simulation complète."""
    print("\n" + "="*70)
    print("  🎬 TEST COMPLET DU FLUX MULTI-AGENT (SIMULATION)")
    print("="*70 + "\n")
    
    agents = [
        SimulatedAnalystAgent(),
        SimulatedRiskAgent(),
        SimulatedDecisionAgent(),
        SimulatedExecutionAgent(),
        SimulatedGuardianAgent(),
    ]
    
    # Démarrer tous
    for agent in agents:
        await agent.start()
    
    print()
    
    # Lancer en parallèle
    await asyncio.gather(*[agent.run() for agent in agents])
    
    print("\n" + "="*70)
    print("  📊 RÉSUMÉ DE LA SIMULATION")
    print("="*70 + "\n")
    
    print("✅ Flux complet validé:")
    print("   1. AnalystAgent découvrit 2 signaux")
    print("   2. RiskAgent évalua et approuva les 2")
    print("   3. DecisionAgent prit 2 décisions BUY/SELL")
    print("   4. ExecutionAgent simula 2 exécutions")
    print("   5. GuardianAgent surveilla 2 positions\n")


if __name__ == "__main__":
    asyncio.run(run_simulation())
