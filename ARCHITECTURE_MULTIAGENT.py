"""
ARCHITECTURE MULTI-AGENT DÉCENTRALISÉE
=====================================

Vue d'ensemble et flux de communication.

AGENTS AUTONOMES (5):
─────────────────

1. AnalystAgent
   - Lit le marché en continu (boucle indépendante)
   - Analyse H1 + M15 avec signal_engine
   - Publie: "signal" (BUY/SELL/WAIT)
   
2. RiskAgent
   - Reçoit signaux de l'Analyst
   - Évalue circuit_breaker, protections, news
   - Publie: "risk_decision" (approved/rejected avec raison)
   
3. DecisionAgent
   - Synthétise signal + risk_decision
   - Décide BUY/SELL final
   - Publie: "buy_signal" ou "sell_signal" à ExecutionAgent
   
4. ExecutionAgent
   - Reçoit décisions approuvées
   - Exécute les ordres via MT5
   - Gère positions et limites
   - Publie: "trade_opened", "trade_closed"
   
5. GuardianAgent
   - Surveille positions ouvertes (boucle indépendante)
   - Détecte reversals, stops, prises de profit
   - Publie: "close_position" ou "guardian_action" à ExecutionAgent


FLUX ASYNCHRONE (NON-BLOQUANT):
────────────────────────────

Market Data (continu)
       │
       ▼
AnalystAgent (autonome)
       │ publie: "signal"
       ▼
RiskAgent (écoute + évalue)
       │ publie: "risk_decision"
       ▼
DecisionAgent (synthétise)
       │ publie: "buy_signal" ou "sell_signal"
       ▼
ExecutionAgent (exécute)
       │ publie: "trade_opened"
       ▼
GuardianAgent (surveille)
       │ publie: "close_position"
       ▼
ExecutionAgent (ferme)


POINTS CLÉS:
───────────

✅ DÉCENTRALISÉ
   - Pas d'orchestrateur central
   - Chaque agent a sa boucle autonome
   - Communication par messages asynchrones

✅ RÉSILIENT
   - Si AnalystAgent crash → RiskAgent continue d'évaluer positions
   - Si ExecutionAgent crash → GuardianAgent surveille toujours
   - Message bus découple les agents

✅ SCALABLE
   - Ajouter un agent = ajouter une classe + l'enregistrer
   - Agents peuvent tourner en parallèle sur CPU cores

✅ AUDITAIRE
   - Tous les messages logés
   - audit_logger capture chaque décision
   - Replay exact possible


MODULES INTÉGRÉS:
────────────────

signal_engine.py        → AnalystAgent.run()
smart_strategies.py     → AnalystAgent.run()
market_protection.py    → RiskAgent._evaluate_risk()
economic_calendar.py    → RiskAgent._evaluate_risk()
circuit_breaker.py      → ExecutionAgent.run() + RiskAgent.run()
mt5_bridge.py           → Tous les agents (via build_broker())
audit_logger.py         → ExecutionAgent._execute_trade()
learning_store.py       → ExecutionAgent (track trades)

SUPPRIMÉ (CODE MORT):
──────────────────

❌ trade_orchestrator.py (orchestrateur centralisé)
❌ agent_core.TradingAgent (old sequential pattern)
❌ Tous les run_bot.py patterns (remplacé par agents_runtime.py)


LANCEMENT:
──────────

    python agents_runtime.py
    
    # Lance automatiquement en parallèle:
    # - AnalystAgent (scan marché)
    # - RiskAgent (évalue risques)
    # - DecisionAgent (synthétise)
    # - ExecutionAgent (exécute)
    # - GuardianAgent (surveille)
    
    # Ctrl+C = arrêt gracieux


CONFIGURATION:
───────────────

settings.py:
  - INSTRUMENTS: ["EURUSDm", "XAUUSDm", "BTCUSDm"]
  - PRIMARY_TIMEFRAME: "H1"
  - CONFIRM_TIMEFRAME: "M15"
  - MAX_RISK_PER_TRADE: 0.02
  - MAX_OPEN_POSITIONS: 3

MONITORING:
───────────

Chaque agent log autonomement:
  [TIMESTAMP] LEVEL | AGENT_NAME | Message
  
Exemple:
  [2026-05-02T11:15:53] INFO | AnalystAgent | EURUSD: Signal BUY (force 4/5)
  [2026-05-02T11:15:54] INFO | RiskAgent    | EURUSD: Approuvé (risque modéré)
  [2026-05-02T11:15:55] INFO | DecisionAgent | EURUSD: DÉCISION BUY
  [2026-05-02T11:15:56] INFO | ExecutionAgent | EURUSD: BUY executé | vol=1.5 | SL=45p TP=90p
  [2026-05-02T11:20:00] INFO | GuardianAgent | EURUSD BUY: CLOSE (objectif atteint)
"""

if __name__ == "__main__":
    print(__doc__)
