"""
CHECKLIST DE VÉRIFICATION — Validez le nouveau système
=====================================================

Exécutez cette checklist pour vérifier que tout fonctionne.
"""

import os
import sys


def check_files_exist():
    """Vérifie que tous les fichiers existent."""
    print("\n1️⃣  VÉRIFICATION DES FICHIERS")
    print("="*70)
    
    required_files = [
        # Framework
        "agent_framework.py",
        # Agents
        "analyst_agent.py",
        "risk_agent.py",
        "decision_agent.py",
        "execution_agent.py",
        "guardian_agent.py",
        # Runtime
        "agents_runtime.py",
        "start_trading_agents.py",
        # Tests
        "test_agents_framework.py",
        "test_multiagent_flow.py",
        "validate_imports.py",
        # Documentation
        "ARCHITECTURE_MULTIAGENT.py",
        "MIGRATION_GUIDE.py",
        "SUMMARY_COMPLETE.py",
    ]
    
    all_exist = True
    for filename in required_files:
        exists = os.path.exists(filename)
        status = "✅" if exists else "❌"
        print(f"{status} {filename}")
        if not exists:
            all_exist = False
    
    return all_exist


def check_no_old_files():
    """Vérifie que les anciens fichiers ont été supprimés."""
    print("\n2️⃣  VÉRIFICATION: CODE MORT SUPPRIMÉ")
    print("="*70)
    
    dead_files = [
        ("trade_orchestrator.py", "Orchestrateur centralisé (mort)"),
        ("agent_core.py", "TradingAgent unique (mort)"),
    ]
    
    all_removed = True
    for filename, description in dead_files:
        exists = os.path.exists(filename)
        if exists:
            # Vérifier si c'est un backup
            if os.path.exists("_backup"):
                print(f"⚠️  {filename} existe toujours (à supprimer, ou déplacer dans _backup/)")
                all_removed = False
            else:
                print(f"❌ {filename} existe toujours (DOIT ÊTRE SUPPRIMÉ)")
                all_removed = False
        else:
            print(f"✅ {filename} supprimé")
    
    return all_removed


def check_imports():
    """Valide tous les imports."""
    print("\n3️⃣  VALIDATION DES IMPORTS")
    print("="*70)
    
    modules = [
        "agent_framework",
        "analyst_agent",
        "risk_agent",
        "decision_agent",
        "execution_agent",
        "guardian_agent",
        "agents_runtime",
    ]
    
    all_ok = True
    for module_name in modules:
        try:
            __import__(module_name)
            print(f"✅ {module_name}")
        except Exception as e:
            print(f"❌ {module_name}: {e}")
            all_ok = False
    
    return all_ok


def check_dependencies():
    """Vérifie que les modules dépendants existent."""
    print("\n4️⃣  VÉRIFICATION DES DÉPENDANCES")
    print("="*70)
    
    dependencies = {
        "signal_engine.py": "Utilisé par AnalystAgent",
        "smart_strategies.py": "Utilisé par AnalystAgent",
        "market_protection.py": "Utilisé par RiskAgent",
        "economic_calendar.py": "Utilisé par RiskAgent",
        "circuit_breaker.py": "Utilisé par RiskAgent + ExecutionAgent",
        "mt5_bridge.py": "Utilisé par tous les agents",
        "audit_logger.py": "Utilisé par ExecutionAgent",
        "learning_store.py": "Utilisé par ExecutionAgent",
    }
    
    all_ok = True
    for filename, usage in dependencies.items():
        exists = os.path.exists(filename)
        status = "✅" if exists else "❌"
        print(f"{status} {filename:30s} {usage}")
        if not exists:
            all_ok = False
    
    return all_ok


def main():
    """Lance la checklist."""
    print("\n" + "="*70)
    print("  ✅ CHECKLIST DE VÉRIFICATION SYSTÈME MULTI-AGENT")
    print("="*70)
    
    results = []
    
    # Exécuter les vérifications
    results.append(("Fichiers créés", check_files_exist()))
    results.append(("Code mort supprimé", check_no_old_files()))
    results.append(("Imports valides", check_imports()))
    results.append(("Dépendances présentes", check_dependencies()))
    
    # Résumé
    print("\n" + "="*70)
    print("  📊 RÉSUMÉ")
    print("="*70 + "\n")
    
    all_passed = True
    for check_name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status:10s} {check_name}")
        if not passed:
            all_passed = False
    
    print("\n" + "="*70)
    if all_passed:
        print("  ✅ SYSTÈME PRÊT POUR LA PRODUCTION")
        print("\n  Démarrage: python start_trading_agents.py")
    else:
        print("  ❌ CORRIGEZ LES ERREURS AVANT DÉMARRAGE")
    print("="*70 + "\n")
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
