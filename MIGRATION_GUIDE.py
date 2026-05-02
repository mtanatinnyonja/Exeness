"""
GUIDE DE MIGRATION: ORCHESTRATEUR CENTRALISÉ → AGENTS DÉCENTRALISÉS
===================================================================

Ce document explique le changement architectural et comment valider le nouveau système.


1. RÉSUMÉ DU CHANGEMENT
─────────────────────

AVANT (Ancien système):
  TradeOrchestrator (main loop)
    ├─ TradingAgent (run_cycle)
    │   ├─ AnalysteLLM → Signal
    │   ├─ RiskManagerLLM → Approved/Rejected
    │   └─ DécideurLLM → BUY/SELL/WAIT
    └─ Attendre 30-60s avant prochain cycle

⚠️  Problèmes:
  ❌ Bloquant — attendu orchestrateur pour chaque décision
  ❌ Single point of failure — Si orchestrateur crash, tout s'arrête
  ❌ Séquentiel — Analyste → Risk → Décideur → Exécution (lent)
  ❌ Difficile à tester — Tous les modules couplés


APRÈS (Nouveau système):
  AnalystAgent (boucle autonome)
    │ publie: "signal"
    ▼
  RiskAgent (boucle autonome, écoute signaux)
    │ publie: "risk_decision"
    ▼
  DecisionAgent (boucle autonome, synthétise)
    │ publie: "buy_signal" ou "sell_signal"
    ▼
  ExecutionAgent (boucle autonome, exécute)
    │ publie: "trade_opened"
    ▼
  GuardianAgent (boucle autonome, surveille)
    │ publie: "close_position"
    ▼
  ExecutionAgent (ferme position)

✅ Avantages:
  ✅ Asynchrone — Non-bloquant, haute concurrence
  ✅ Résilient — Agents indépendants, continuent même si l'un crash
  ✅ Parallèle — Tous les agents tournent simultanément
  ✅ Testable — Agents isolés, MessageBus mockable
  ✅ Observable — Chaque agent log autonomement


2. FICHIERS CRÉÉS (NOUVEAUX)
────────────────────────────

agent_framework.py
  └─ Classe Agent abstraite
  └─ Classe MessageBus asynchrone
  └─ Message dataclass

analyst_agent.py
  └─ AnalystAgent autonome
  └─ Scan marché en continu
  └─ Publie signaux

risk_agent.py
  └─ RiskAgent autonome
  └─ Évalue circuit_breaker, protections, news
  └─ Publie décisions risque

decision_agent.py
  └─ DecisionAgent autonome
  └─ Synthétise signal + risk_decision
  └─ Publie décisions finales BUY/SELL

execution_agent.py
  └─ ExecutionAgent autonome
  └─ Exécute ordres approuvés
  └─ Surveille limites, gère positions
  └─ Publie trade_opened/closed

guardian_agent.py
  └─ GuardianAgent autonome
  └─ Surveille positions ouvertes
  └─ Détecte reversals et stops
  └─ Publie close_position

agents_runtime.py
  └─ Démarre tous les agents en parallèle
  └─ Gère arrêt gracieux
  └─ Point d'entrée principal

start_trading_agents.py
  └─ Script de démarrage simple
  └─ Usage: python start_trading_agents.py

validate_imports.py
  └─ Valide que tous les modules s'importent
  └─ Utile pour debugging

ARCHITECTURE_MULTIAGENT.py
  └─ Documentation visuelle
  └─ Flux de communication


3. FICHIERS SUPPRIMÉS (CODE MORT)
──────────────────────────────────

❌ trade_orchestrator.py
   - Orchestrateur centralisé, incompatible
   - Archivé dans _backup/

❌ agent_core.py (TradingAgent)
   - Ancien pattern synchrone
   - Remplacé par 5 agents indépendants


4. MODULES RÉUTILISÉS (INTÉGRATION)
──────────────────────────────────────

Les modules suivants CONTINUENT DE FONCTIONNER, intégrés aux nouveaux agents:

signal_engine.py
  └─ Utilisé par: AnalystAgent._analyze_instrument()
  └─ Fonction: calculate_signal_score()

smart_strategies.py
  └─ Utilisé par: AnalystAgent._analyze_instrument()
  └─ Fonction: build_strategies_context()

market_protection.py
  └─ Utilisé par: RiskAgent._evaluate_risk()
  └─ Fonction: run_all_protections()

economic_calendar.py
  └─ Utilisé par: RiskAgent._evaluate_risk()
  └─ Fonction: should_pause_trading()

circuit_breaker.py
  └─ Utilisé par: RiskAgent._evaluate_risk() + ExecutionAgent.run()
  └─ Fonction: can_trade()

mt5_bridge.py
  └─ Utilisé par: TOUS les agents
  └─ Fonction: build_broker()

audit_logger.py
  └─ Utilisé par: ExecutionAgent._execute_trade()
  └─ Fonction: log_execution()

learning_store.py
  └─ Utilisé par: ExecutionAgent (track trades)
  └─ Classe: AgentMemory

dynamic_risk_manager.py
  └─ Optionnel: Peut être intégré dans RiskAgent/ExecutionAgent

performance_tracker.py
  └─ Optionnel: Monitoring des trades


5. FLUX DE COMMUNICATION
───────────────────────

Message Types:
  "signal"         → AnalystAgent → Broadcast
  "risk_decision"  → RiskAgent → Broadcast
  "buy_signal"     → DecisionAgent → ExecutionAgent
  "sell_signal"    → DecisionAgent → ExecutionAgent
  "trade_opened"   → ExecutionAgent → Broadcast
  "close_position" → GuardianAgent → ExecutionAgent
  "trade_closed"   → ExecutionAgent → Broadcast


6. VALIDATION ET TEST
────────────────────

Étape 1: Valider les imports
  $ python validate_imports.py
  
  Résultat attendu: "TOUS les imports réussis!"

Étape 2: Tester le framework de communication
  $ python test_agents_framework.py
  
  Résultat attendu: 
    - 2 agents envoient/reçoivent 3 messages chacun
    - Pas d'erreur, arrêt gracieux

Étape 3: Démarrer les agents en mode test (OPTIONNEL)
  $ python start_trading_agents.py
  
  Résultat attendu:
    - 5 agents démarrés
    - AnalystAgent scanne marché
    - Messages circulent entre agents
    - Ctrl+C arrête proprement


7. CONFIGURATION
────────────────

Aucun changement nécessaire dans settings.py

Les agents lisent:
  - INSTRUMENTS
  - PRIMARY_TIMEFRAME
  - CONFIRM_TIMEFRAME
  - MAX_RISK_PER_TRADE
  - MAX_OPEN_POSITIONS
  - DAILY_LOSS_LIMIT
  - Etc.


8. MONITORING
─────────────

Chaque agent log en temps réel:
  [TIMESTAMP] LEVEL | AGENT_NAME | Message
  
Exemple de logs attendus:
  [2026-05-02T11:15:53] INFO | AnalystAgent | EURUSD: Signal BUY (force 4/5)
  [2026-05-02T11:15:54] INFO | RiskAgent    | EURUSD: Approuvé (risque modéré)
  [2026-05-02T11:15:55] INFO | DecisionAgent | EURUSD: DÉCISION BUY (conf 80%)
  [2026-05-02T11:15:56] INFO | ExecutionAgent | EURUSD: BUY executé | vol=1.5 | SL=45p TP=90p
  [2026-05-02T11:20:00] INFO | GuardianAgent | EURUSD BUY: CLOSE (objectif atteint: $150)


9. ROLLBACK (SI NÉCESSAIRE)
───────────────────────────

Si vous avez besoin de revenir à l'ancien système:
  1. Récupérer trade_orchestrator.py depuis _backup/
  2. Récupérer agent_core.py depuis version antérieure
  3. Commenter les imports des agents dans main.py
  
⚠️  NON RECOMMANDÉ — La nouvelle architecture est supérieure


10. SUPPORT ET DEBUGGING
────────────────────────

Si un agent ne démarre pas:
  1. Vérifier les logs (TIMESTAMP + LEVEL + AGENT_NAME)
  2. Vérifier les imports: python validate_imports.py
  3. Vérifier que MT5 et Ollama sont accessibles
  4. Vérifier settings.py

Si les messages ne circulent pas:
  1. Vérifier que le MessageBus est initialisé (get_message_bus())
  2. Vérifier que les agents sont abonnés aux bons event_types
  3. Vérifier que await.send_message() est appelé (pas return sans await)

Si un agent crash:
  1. Lire le traceback
  2. Les autres agents continuent (test de résilience)
  3. Correction: Améliorer le try/except du agent fautif
"""

if __name__ == "__main__":
    print(__doc__)
