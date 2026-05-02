#!/usr/bin/env python3
"""
POINT D'ENTRÉE PRINCIPAL — Système Multi-Agent Décentralisé
===========================================================

Démarre tous les agents autonomes en parallèle asynchrone.

Usage:
    python start_trading_agents.py        # Démarrage normal
    python start_trading_agents.py test   # Mode test (simulation)

Agents démarrés:
    ✅ AnalystAgent      — Scanne marché en continu
    ✅ RiskAgent         — Évalue risques
    ✅ DecisionAgent     — Synthétise + décide
    ✅ ExecutionAgent    — Exécute ordres
    ✅ GuardianAgent     — Surveille positions

Arrêt:
    Ctrl+C = Arrêt gracieux de tous les agents
"""

import sys
import asyncio
from agents_runtime import AgentsRuntime


def main():
    """Point d'entrée."""
    print(__doc__)
    
    # Lancer le runtime
    runtime = AgentsRuntime()
    
    try:
        asyncio.run(runtime.start())
    except KeyboardInterrupt:
        print("\n⏹️  Arrêt gracieux...")
        asyncio.run(runtime.stop())
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Erreur fatale: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
