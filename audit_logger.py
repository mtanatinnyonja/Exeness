"""
Audit trail complet pour tracer chaque décision agent, exécution et erreur.
Permet de rejouer les décisions et déboguer les erreurs.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional, List


class AuditLogger:
    """Enregistre chaque événement dans un fichier horodaté."""

    def __init__(self, audit_dir: str = "data/audit"):
        self.audit_dir = Path(audit_dir)
        self.audit_dir.mkdir(parents=True, exist_ok=True)
        self.current_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self.audit_file = self.audit_dir / f"audit_{self.current_date}.jsonl"

    def _get_timestamp(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _ensure_current_date(self):
        """Change de fichier si on a changé de jour."""
        new_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if new_date != self.current_date:
            self.current_date = new_date
            self.audit_file = self.audit_dir / f"audit_{self.current_date}.jsonl"

    def _write_record(self, record: Dict[str, Any]):
        """Écrit un record en JSONL (une ligne par événement)."""
        self._ensure_current_date()
        try:
            with open(self.audit_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as e:
            print(f"[AUDIT ERROR] Impossible d'écrire le record: {e}")

    def log_decision(self, instrument: str, agent_name: str, decision: Dict, context: Optional[Dict] = None):
        """Trace une décision d'agent avec contexte complet."""
        record = {
            "timestamp": self._get_timestamp(),
            "event_type": "agent_decision",
            "instrument": instrument,
            "agent": agent_name,
            "decision": decision,
        }
        if context:
            record["context"] = {
                "signal_score": context.get("signal_score"),
                "spread": context.get("spread"),
                "market_regime": context.get("market_regime"),
                "balance": context.get("balance"),
                "open_positions": context.get("open_positions"),
            }
        self._write_record(record)

    def log_execution(self, instrument: str, direction: str, volume: float, 
                      entry: float, sl: float, tp: float, order_id: str = ""):
        """Trace l'exécution d'un ordre."""
        record = {
            "timestamp": self._get_timestamp(),
            "event_type": "trade_executed",
            "instrument": instrument,
            "direction": direction,
            "volume": volume,
            "entry_price": entry,
            "stop_loss": sl,
            "take_profit": tp,
            "order_id": order_id,
        }
        self._write_record(record)

    def log_position_closed(self, instrument: str, direction: str, entry: float, 
                           exit_price: float, pnl: float, reason: str = ""):
        """Trace la fermeture d'une position."""
        record = {
            "timestamp": self._get_timestamp(),
            "event_type": "position_closed",
            "instrument": instrument,
            "direction": direction,
            "entry_price": entry,
            "exit_price": exit_price,
            "pnl": pnl,
            "reason": reason,
        }
        self._write_record(record)

    def log_error(self, module: str, error: str, context: Optional[Dict] = None):
        """Trace une erreur avec contexte."""
        record = {
            "timestamp": self._get_timestamp(),
            "event_type": "error",
            "module": module,
            "error_message": str(error),
        }
        if context:
            record["context"] = context
        self._write_record(record)

    def log_risk_event(self, event_type: str, reason: str, data: Optional[Dict] = None):
        """Trace des événements de risque (circuit breaker, limite de perte, etc)."""
        record = {
            "timestamp": self._get_timestamp(),
            "event_type": f"risk_{event_type}",
            "reason": reason,
        }
        if data:
            record["data"] = data
        self._write_record(record)

    def log_llm_call(self, instrument: str, agent: str, prompt_tokens: int, 
                     completion_tokens: int, response_time_sec: float):
        """Trace les appels LLM pour budget tracking."""
        record = {
            "timestamp": self._get_timestamp(),
            "event_type": "llm_call",
            "instrument": instrument,
            "agent": agent,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "response_time_sec": response_time_sec,
        }
        self._write_record(record)

    def get_session_trades(self) -> List[Dict]:
        """Récupère tous les trades exécutés dans la session."""
        trades = []
        try:
            with open(self.audit_file, "r", encoding="utf-8") as f:
                for line in f:
                    record = json.loads(line)
                    if record.get("event_type") == "trade_executed":
                        trades.append(record)
        except Exception:
            pass
        return trades

    def get_session_errors(self) -> List[Dict]:
        """Récupère tous les erreurs de la session."""
        errors = []
        try:
            with open(self.audit_file, "r", encoding="utf-8") as f:
                for line in f:
                    record = json.loads(line)
                    if record.get("event_type") == "error":
                        errors.append(record)
        except Exception:
            pass
        return errors

    def get_daily_stats(self) -> Dict:
        """Retourne les stats du jour (trades, erreurs, LLM calls)."""
        trades = self.get_session_trades()
        errors = self.get_session_errors()
        
        llm_calls = 0
        total_tokens = 0
        try:
            with open(self.audit_file, "r", encoding="utf-8") as f:
                for line in f:
                    record = json.loads(line)
                    if record.get("event_type") == "llm_call":
                        llm_calls += 1
                        total_tokens += record.get("prompt_tokens", 0) + record.get("completion_tokens", 0)
        except Exception:
            pass

        return {
            "trades_executed": len(trades),
            "errors_count": len(errors),
            "llm_calls": llm_calls,
            "total_tokens": total_tokens,
        }


# Singleton global
_audit_logger = None


def get_audit_logger() -> AuditLogger:
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger()
    return _audit_logger
