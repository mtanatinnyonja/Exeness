"""
Validation des imports du système multi-agent.
Vérifie que tous les modules peuvent être importés sans erreurs.
"""

import sys


def validate_imports():
    """Valide tous les imports."""
    print("\n" + "="*70)
    print("  ✓ VALIDATION DES IMPORTS")
    print("="*70 + "\n")
    
    modules = [
        ("agent_framework", "Framework de base + MessageBus"),
        ("analyst_agent", "Agent Analyste"),
        ("risk_agent", "Agent Risk Manager"),
        ("decision_agent", "Agent Décideur"),
        ("execution_agent", "Agent Exécution"),
        ("guardian_agent", "Agent Gardien"),
        ("agents_runtime", "Runtime des agents"),
    ]
    
    failed = []
    
    for module_name, description in modules:
        try:
            __import__(module_name)
            print(f"✅ {module_name:25s} — {description}")
        except ImportError as e:
            print(f"❌ {module_name:25s} — {description}")
            print(f"   Erreur: {e}")
            failed.append((module_name, str(e)))
        except Exception as e:
            print(f"⚠️  {module_name:25s} — {description}")
            print(f"   Avertissement: {e}")
    
    print("\n" + "="*70)
    
    if failed:
        print(f"\n❌ {len(failed)} module(s) ont échoué:\n")
        for module_name, error in failed:
            print(f"  - {module_name}")
            print(f"    {error}\n")
        return False
    else:
        print("\n✅ TOUS les imports réussis!\n")
        return True


if __name__ == "__main__":
    success = validate_imports()
    sys.exit(0 if success else 1)
