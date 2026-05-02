"""
AUDIT DE CODE MORT — Analyse complète
======================================

Identifie tous les fichiers inutilisés.
"""

DEAD_CODE_ANALYSIS = """

🔴 FICHIERS À SUPPRIMER (Code mort — NON utilisés)
═══════════════════════════════════════════════════

1. ENTRY POINTS OBSOLÈTES:
   ❌ main.py ......................... Ancien point d'entrée
   ❌ run_bot.py ...................... Ancien point d'entrée
      → REMPLACÉ PAR: start_trading_agents.py + agents_runtime.py

2. PROMPTS LLM (Remplacés par agents individuels):
   ❌ agent_communication.py ........... Old prompt builders pour LLM
      → REMPLACÉ PAR: prompt logic intégré dans chaque agent

3. TESTS OBSOLÈTES (Validaient l'old architecture):
   ❌ test_core.py .................... Old test (agent_core.TradingAgent)
   ❌ test_ai_enhancements.py ......... Old test (améliorations old system)
   ❌ test_improvements.py ............ Old test (validation vieux modules)
      → REMPLACÉ PAR: test_agents_framework.py + test_multiagent_flow.py

4. SCRIPTS LEGACY:
   ❌ start_local.ps1 ................. Old startup script Windows
      → REMPLACÉ PAR: start_trading_agents.py

5. PLANIFICATION OBSOLÈTE:
   ❌ trade_planner.py ............... Unclear purpose, unused in new system
      → À VÉRIFIER ou SUPPRIMER

6. DÉMOS/QUICKSTART (Documentation, pas du code actif):
   ⚠️  QUICKSTART_IMPROVEMENTS.py ..... Demo pour old system (peut être supprimé)


🟡 FICHIERS DOCUMENTATION (Utiles pour référence, pas du code exécuté)
═════════════════════════════════════════════════════════════════════

Ces fichiers sont de la DOCUMENTATION, pas du code actif:
   ⚠️  ARCHITECTURE_MULTIAGENT.py .... Architecture overview (utile, garder)
   ⚠️  MIGRATION_GUIDE.py ............ Migration doc (utile, garder)
   ⚠️  SUMMARY_COMPLETE.py ........... Résumé (utile, garder)
   ⚠️  STRUCTURE_PROJECT.py .......... Structure (utile, garder)
   ⚠️  VERSION_SUMMARY.md ............ Old doc (peut être supprimé)
   ⚠️  IMPROVEMENTS.md ............... Old doc (peut être supprimé)
   ⚠️  README.md ..................... Old README (remplacé par README_MULTIAGENT.md)


🟠 FICHIERS OPTIONNELS (Pas critiques pour core trading)
════════════════════════════════════════════════════════

Ces modules ne sont PAS appelés par les agents:
   ⚠️  control_panel.py .............. Web dashboard (OPTIONNEL)
   ⚠️  dashboard.py .................. Web interface (OPTIONNEL)
   ⚠️  telegram_notifier.py .......... Notifications (OPTIONNEL)


🟢 FICHIERS CRITIQUES (À GARDER)
════════════════════════════════

FRAMEWORK & AGENTS:
   ✅ agent_framework.py ............ BASE — INDISPENSABLE
   ✅ analyst_agent.py .............. AGENT — INDISPENSABLE
   ✅ risk_agent.py ................. AGENT — INDISPENSABLE
   ✅ decision_agent.py ............. AGENT — INDISPENSABLE
   ✅ execution_agent.py ............ AGENT — INDISPENSABLE
   ✅ guardian_agent.py ............. AGENT — INDISPENSABLE
   ✅ agents_runtime.py ............. CORE LAUNCHER — INDISPENSABLE
   ✅ start_trading_agents.py ....... ENTRY POINT — INDISPENSABLE

MODULES D'ANALYSE & PROTECTION:
   ✅ signal_engine.py .............. Core signals — INDISPENSABLE
   ✅ smart_strategies.py ........... Confluence — INDISPENSABLE
   ✅ market_protection.py .......... Protections — INDISPENSABLE
   ✅ economic_calendar.py .......... News filter — INDISPENSABLE
   ✅ circuit_breaker.py ............ Auto-pause — INDISPENSABLE
   ✅ dynamic_risk_manager.py ....... Risk adapt — INDISPENSABLE

MODULES AUXILIAIRES:
   ✅ mt5_bridge.py ................. Broker API — INDISPENSABLE
   ✅ learning_store.py ............. Trade memory — INDISPENSABLE
   ✅ audit_logger.py ............... Decisions log — INDISPENSABLE
   ✅ settings.py ................... Configuration — INDISPENSABLE
   ✅ runtime_db.py ................. Persistent config — INDISPENSABLE
   ✅ market_context.py ............. Market data — UTILISÉ
   ✅ signal_filter.py .............. Signal filters — UTILISÉ
   ✅ performance_tracker.py ........ Stats — UTILISÉ
   ✅ backtest.py ................... Backtesting — OPTIONNEL mais utile

TESTS & VALIDATION:
   ✅ test_agents_framework.py ...... Framework test — UTILE
   ✅ test_multiagent_flow.py ....... Flow test — UTILE
   ✅ validate_imports.py ........... Import validation — UTILE
   ✅ checklist_system.py ........... Global validation — UTILE

DOCUMENTATION CORE:
   ✅ README_MULTIAGENT.md .......... README principal — IMPORTANT

DATA:
   ✅ data/ ......................... Data storage — INDISPENSABLE


RÉSUMÉ
══════

🔴 À SUPPRIMER (Code mort):
   - main.py
   - run_bot.py
   - agent_communication.py
   - test_core.py
   - test_ai_enhancements.py
   - test_improvements.py
   - start_local.ps1
   - trade_planner.py (à vérifier)
   - QUICKSTART_IMPROVEMENTS.py (demo)
   - VERSION_SUMMARY.md (old doc)
   - IMPROVEMENTS.md (old doc)
   - README.md (old README)
   
   TOTAL: 12 fichiers morts

⚠️  À GARDER OPTIONNELS:
   - control_panel.py (dashboard)
   - dashboard.py (web UI)
   - telegram_notifier.py (notifications)
   - ARCHITECTURE_MULTIAGENT.py (doc utile)
   - MIGRATION_GUIDE.py (doc utile)
   - SUMMARY_COMPLETE.py (doc utile)
   - STRUCTURE_PROJECT.py (doc utile)

✅ À GARDER OBLIGATOIRE:
   - 8 agents + framework
   - 8 modules d'analyse/protection
   - 8+ modules auxiliaires
   - 4 tests
   - settings, data

VERDICT: ~50% du code est "mort" et peut être supprimé
"""

if __name__ == "__main__":
    print(DEAD_CODE_ANALYSIS)
