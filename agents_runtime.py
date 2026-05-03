"""
Runtime des agents IA — Lance tous les agents en parallèle asynchrone.
Système spécialisé XAUUSDm (Or / XAUUSD).
"""

import asyncio
import signal
import sys
from typing import List

from agent_framework import Agent
from analyst_agent import AnalystAgent
from risk_agent import RiskAgent
from decision_agent import DecisionAgent
from execution_agent import ExecutionAgent
from guardian_agent import GuardianAgent


class AgentsRuntime:
    """Orchestre tous les agents autonomes."""
    
    def __init__(self):
        self.agents: List[Agent] = [
            AnalystAgent(),
            RiskAgent(),
            DecisionAgent(),
            ExecutionAgent(),
            GuardianAgent(),
        ]
        self.running = False
    
    async def start(self):
        """Démarre tous les agents."""
        self.running = True
        print("\n" + "="*70)
        print("  � EXENESS XAUUSDm SPECIALIST — $100 DEMO — DÉMARRAGE")
        print("="*70 + "\n")
        
        # Démarrer chaque agent
        for agent in self.agents:
            await agent.start()
        
        print(f"✅ {len(self.agents)} agents démarrés en parallèle\n")
        
        # Lancer les boucles asynchrones
        tasks = [agent.run() for agent in self.agents]
        await asyncio.gather(*tasks)
    
    async def stop(self):
        """Arrête tous les agents."""
        print("\n⏹️  Arrêt des agents...")
        for agent in self.agents:
            await agent.stop()
        self.running = False
        print("✅ Tous les agents arrêtés\n")


async def main():
    """Point d'entrée principal."""
    runtime = AgentsRuntime()
    
    # Handle SIGINT (Ctrl+C)
    def signal_handler(sig, frame):
        print("\n\n⏹️  Interruption détectée...")
        asyncio.create_task(runtime.stop())
    
    signal.signal(signal.SIGINT, signal_handler)
    
    try:
        await runtime.start()
    except KeyboardInterrupt:
        await runtime.stop()
    except Exception as e:
        print(f"\n❌ Erreur fatale: {e}")
        await runtime.stop()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
