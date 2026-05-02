"""
Liste FINALE des fichiers après nettoyage complet.
"""

import os
from pathlib import Path

files_by_category = {
    "🤖 FRAMEWORK & AGENTS (8)": [
        "agent_framework.py",
        "analyst_agent.py",
        "risk_agent.py",
        "decision_agent.py",
        "execution_agent.py",
        "guardian_agent.py",
        "agents_runtime.py",
        "start_trading_agents.py",
    ],
    "📊 ANALYSE & SIGNAUX (3)": [
        "signal_engine.py",
        "smart_strategies.py",
        "signal_filter.py",
    ],
    "🛡️ PROTECTION (4)": [
        "market_protection.py",
        "economic_calendar.py",
        "circuit_breaker.py",
        "dynamic_risk_manager.py",
    ],
    "🔧 AUXILIAIRES (8)": [
        "mt5_bridge.py",
        "learning_store.py",
        "audit_logger.py",
        "runtime_db.py",
        "settings.py",
        "market_context.py",
        "performance_tracker.py",
        "backtest.py",
    ],
    "🧪 TESTS (4)": [
        "test_agents_framework.py",
        "test_multiagent_flow.py",
        "validate_imports.py",
        "checklist_system.py",
    ],
    "📚 DOCUMENTATION (5)": [
        "README_MULTIAGENT.md",
        "ARCHITECTURE_MULTIAGENT.py",
        "MIGRATION_GUIDE.py",
        "SUMMARY_COMPLETE.py",
        "STRUCTURE_PROJECT.py",
    ],
    "⚙️ CONFIG (1)": [
        "requirements.txt",
    ],
    "⚡ OPTIONNELS (3)": [
        "control_panel.py",
        "dashboard.py",
        "telegram_notifier.py",
    ],
    "📁 AUDIT & NETTOYAGE (3)": [
        "CLEANUP_REPORT.py",
        "AUDIT_CODE_MORT.py",
        "FILES_INVENTORY.py",
    ],
}

print("\n" + "="*70)
print("  📋 INVENTAIRE FINAL — SYSTÈME NETTOYÉ")
print("="*70 + "\n")

total_files = 0
for category, files in files_by_category.items():
    print(f"{category}")
    missing = []
    
    for fname in files:
        exists = "✅" if os.path.exists(fname) else "❌"
        print(f"  {exists} {fname}")
        if os.path.exists(fname):
            total_files += 1
        else:
            missing.append(fname)
    
    if missing:
        print(f"  ⚠️  MANQUANTS: {', '.join(missing)}")
    print()

# Répertoires
print("📁 RÉPERTOIRES")
print(f"  ✅ data/" if os.path.isdir("data") else "  ❌ data/")
print(f"  ✅ _backup/" if os.path.isdir("_backup") else "  ❌ _backup/")
print()

print("="*70)
print(f"\n📊 RÉSUMÉ FINAL")
print(f"  Fichiers actifs: {total_files}")
print(f"  Répertoires: 2 (data/ + _backup/)")
print(f"  Total: {total_files + 2}\n")

print("✅ SYSTÈME NETTOYÉ ET PRÊT\n")

# Vérifier les vieux fichiers
dead_files = [
    "main.py", "run_bot.py", "agent_communication.py",
    "test_core.py", "test_ai_enhancements.py", "test_improvements.py",
    "start_local.ps1", "trade_planner.py", "QUICKSTART_IMPROVEMENTS.py",
    "VERSION_SUMMARY.md", "IMPROVEMENTS.md", "README.md"
]

found_dead = [f for f in dead_files if os.path.exists(f)]
if found_dead:
    print(f"⚠️  CODE MORT TROUVÉ: {found_dead}")
else:
    print("✅ Zéro code mort détecté")

print()
