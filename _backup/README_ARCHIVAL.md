/**
 * ARCHIVED FILES - MIGRATION TO DECENTRALIZED MULTI-AGENT ARCHITECTURE
 * ====================================================================
 * 
 * Les fichiers suivants ont été ARCHIVÉS car incompatibles avec la nouvelle
 * architecture décentralisée:
 * 
 * 1. trade_orchestrator.py (REMOVED)
 *    - Ancien pattern: Orchestrateur centralisé qui contrôle tout
 *    - Raison: Crée une dépendance séquentielle bloquante
 *    - Remplacé par: agents_runtime.py + agents autonomes
 * 
 * 2. agent_core.TradingAgent (REMOVED)
 *    - Ancien pattern: Un seul agent avec méthodes run_cycle() synchrones
 *    - Raison: Pas autonome, contrôlé par l'orchestrateur
 *    - Remplacé par: 5 agents indépendants (Analyst, Risk, Decision, Execution, Guardian)
 * 
 * 
 * NOUVELLE ARCHITECTURE:
 * ─────────────────────
 * 
 * agent_framework.py      → Base Agent class + MessageBus
 * analyst_agent.py        → Scan marché autonome
 * risk_agent.py           → Évalue risques
 * decision_agent.py       → Synthétise + décide
 * execution_agent.py      → Exécute ordres
 * guardian_agent.py       → Surveille positions
 * agents_runtime.py       → Lance tous les agents en parallèle
 * 
 * 
 * AVANTAGES:
 * ─────────
 * 
 * ✅ Décentralisé       → Pas de single point of failure
 * ✅ Asynchrone         → Non-bloquant, haute concurrence
 * ✅ Résilient          → Si un agent crash, les autres continuent
 * ✅ Scalable           → Ajouter des agents sans refactorer
 * ✅ Observable         → Chaque agent log autonomement
 * ✅ Testable           → Agents isolés, MessageBus mockable
 * 
 * 
 * SI VOUS AVEZ BESOIN DES ANCIENS FICHIERS:
 * ──────────────────────────────────────────
 * 
 * Versions de backup disponibles dans _backup/
 * (Note: Ne pas recommandé — la nouvelle architecture est supérieure)
 */
