"""
Helper pour logging d'erreurs standardisé.
Remplace tous les 'except Exception: pass' silencieux par du logging traçable.
"""

import traceback
from typing import Optional, Callable, Any
from audit_logger import get_audit_logger


class SafeExecutor:
    """Exécute une fonction avec logging d'erreur standardisé."""

    def __init__(self, module_name: str = "unknown"):
        self.module = module_name
        self.audit = get_audit_logger()

    def execute(
        self,
        func: Callable,
        context_label: str = "",
        default_return: Any = None,
        critical: bool = False,
    ) -> Any:
        """
        Exécute une fonction avec try/except + audit logging.
        
        Args:
            func: Fonction à exécuter (sans args)
            context_label: Description de ce qu'on fait (ex: "place_order_EURUSD")
            default_return: Valeur à retourner en cas d'erreur
            critical: Si True, log comme erreur critique
        
        Returns:
            Résultat de func ou default_return si erreur
        """
        try:
            return func()
        except Exception as e:
            error_msg = f"{self.module}: {context_label} — {str(e)}"
            
            # Log dans audit trail
            self.audit.log_error(
                self.module,
                error_msg,
                context={
                    "context": context_label,
                    "traceback": traceback.format_exc()[-200:],  # Dernières 200 chars
                }
            )
            
            # Si critique, logger aussi en stdout pour visibilité
            if critical:
                print(f"❌ CRITICAL [{self.module}] {context_label}: {e}")
            
            return default_return


# Singleton par module
_executors = {}


def get_safe_executor(module_name: str) -> SafeExecutor:
    """Récupère ou crée un SafeExecutor pour un module."""
    if module_name not in _executors:
        _executors[module_name] = SafeExecutor(module_name)
    return _executors[module_name]
