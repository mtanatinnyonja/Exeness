"""
Stockage runtime local: configuration modifiable depuis l'interface
et base SQLite pour l'apprentissage des signaux.
"""

import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict

from settings import (
    RUNTIME_DB_FILE, AI_PROVIDER, LOCAL_LLM_ENDPOINT, LOCAL_LLM_MODEL, LOCAL_LLM_TIMEOUT,
    SYMBOL_SOURCE_MODE, PREFERRED_SYMBOLS, MT5_MAX_VISIBLE_SYMBOLS,
    ALLOW_TRADE_EXECUTION, MAX_RISK_PER_TRADE, CHECK_INTERVAL_MINUTES,
    MAX_LLM_CALLS_PER_DAY, DAILY_TOKEN_BUDGET, DASHBOARD_PORT,
    LLM_TEMPERATURE, LLM_MIN_CONFIDENCE, LLM_ANALYSIS_MODE,
    LLM_ANALYSIS_NOTES, LLM_MAX_CONTEXT_BARS,
    DAILY_TARGET, DAILY_LOSS_LIMIT, MAX_OPEN_POSITIONS,
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, SYMBOL_SELECTION_MODE,
)


class RuntimeStore:
    def __init__(self, db_path: str = RUNTIME_DB_FILE):
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    def _connect(self):
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ml_samples (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    instrument TEXT,
                    score REAL,
                    direction TEXT,
                    rsi REAL,
                    macd REAL,
                    spread REAL,
                    decision TEXT,
                    confidence REAL
                )
                """
            )

    def _defaults(self) -> Dict[str, Any]:
        return {
            "ai_provider_requested": "ollama",
            "local_llm_endpoint": LOCAL_LLM_ENDPOINT,
            "local_llm_model": LOCAL_LLM_MODEL,
            "local_llm_timeout": int(LOCAL_LLM_TIMEOUT),
            "symbol_source_mode": "visible",
            "preferred_symbols": list(PREFERRED_SYMBOLS),
            "max_symbols_per_cycle": int(MT5_MAX_VISIBLE_SYMBOLS),
            "allow_trade_execution": bool(ALLOW_TRADE_EXECUTION),
            "max_risk_per_trade": float(MAX_RISK_PER_TRADE),
            "daily_target": float(DAILY_TARGET),
            "daily_loss_limit": float(DAILY_LOSS_LIMIT),
            "max_open_positions": int(MAX_OPEN_POSITIONS),
            "check_interval_minutes": int(CHECK_INTERVAL_MINUTES),
            "max_llm_calls_per_day": int(MAX_LLM_CALLS_PER_DAY),
            "daily_token_budget": int(DAILY_TOKEN_BUDGET),
            "dashboard_port": int(DASHBOARD_PORT),
            "llm_temperature": float(LLM_TEMPERATURE),
            "llm_min_confidence": float(LLM_MIN_CONFIDENCE),
            "llm_analysis_mode": str(LLM_ANALYSIS_MODE),
            "llm_analysis_notes": str(LLM_ANALYSIS_NOTES),
            "llm_context_bars": int(LLM_MAX_CONTEXT_BARS),
            "telegram_enabled": True,
            "telegram_bot_token": TELEGRAM_BOT_TOKEN,
            "telegram_chat_id": TELEGRAM_CHAT_ID,
            "symbol_selection_mode": SYMBOL_SELECTION_MODE,
        }

    def _clean_symbol(self, raw: Any) -> str:
        original = str(raw).strip().replace(" ", "").replace("/", "").replace("\\", "").replace("_", "")
        value = original.upper()
        aliases = {
            "GOLD": "XAUUSD",
            "XAU": "XAUUSD",
            "BTC": "BTCUSD",
            "ETH": "ETHUSD",
            "EUROUSD": "EURUSD",
        }
        return aliases.get(value, original)

    def _normalize(self, key: str, value: Any) -> Any:
        if key in {"allow_trade_execution", "telegram_enabled"}:
            if isinstance(value, str):
                return value.strip().lower() in {"1", "true", "yes", "on"}
            return bool(value)
        if key in {"max_symbols_per_cycle", "check_interval_minutes", "max_llm_calls_per_day", "daily_token_budget", "dashboard_port", "llm_context_bars", "max_open_positions", "local_llm_timeout"}:
            return int(value)
        if key in {"max_risk_per_trade", "llm_temperature", "llm_min_confidence", "daily_target", "daily_loss_limit"}:
            return float(value)
        if key in {"preferred_symbols"}:
            if isinstance(value, str):
                return [self._clean_symbol(s) for s in value.split(",") if str(s).strip()]
            return [self._clean_symbol(s) for s in list(value)]
        if key in {"ai_provider_requested", "symbol_source_mode", "local_llm_endpoint", "local_llm_model", "llm_analysis_mode", "llm_analysis_notes", "telegram_bot_token", "telegram_chat_id", "symbol_selection_mode"}:
            return str(value).strip()
        return value

    def get_settings(self) -> Dict[str, Any]:
        settings = self._defaults()
        with self._connect() as conn:
            rows = conn.execute("SELECT key, value FROM settings").fetchall()
        for key, raw in rows:
            try:
                parsed = json.loads(raw)
            except Exception:
                parsed = raw
            settings[key] = parsed

        legacy_map = {
            "gemini_model": "local_llm_model",
            "claude_model": "local_llm_model",
            "max_api_calls_per_day": "max_llm_calls_per_day",
        }
        for old_key, new_key in legacy_map.items():
            if old_key in settings and new_key not in settings:
                settings[new_key] = settings[old_key]

        settings["ai_provider_requested"] = "ollama"
        settings["symbol_source_mode"] = "visible"
        return settings

    def update_settings(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        allowed_keys = set(self._defaults().keys())
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            for key, value in payload.items():
                if key not in allowed_keys:
                    continue
                normalized = self._normalize(key, value)
                conn.execute(
                    "INSERT INTO settings(key, value, updated_at) VALUES (?, ?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                    (key, json.dumps(normalized, ensure_ascii=False), now),
                )
        return self.get_settings()

    def record_signal_sample(self, instrument: str, signal: Dict[str, Any], spread: float, decision: Dict[str, Any]):
        details = signal.get("details", {})
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO ml_samples(ts, instrument, score, direction, rsi, macd, spread, decision, confidence)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    datetime.now(timezone.utc).isoformat(),
                    instrument,
                    float(signal.get("score", 0)),
                    signal.get("direction"),
                    float(details.get("rsi", 0) or 0),
                    float(details.get("macd", 0) or 0),
                    float(spread or 0),
                    decision.get("decision") if isinstance(decision, dict) else None,
                    float((decision or {}).get("confidence", 0) or 0),
                ),
            )

    def get_ml_stats(self) -> Dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*), COALESCE(AVG(score),0), COALESCE(AVG(confidence),0) FROM ml_samples"
            ).fetchone()
            last = conn.execute(
                "SELECT instrument, decision, ts FROM ml_samples ORDER BY id DESC LIMIT 1"
            ).fetchone()

        return {
            "samples": int(row[0] or 0),
            "avg_score": round(float(row[1] or 0), 2),
            "avg_confidence": round(float(row[2] or 0), 2),
            "last_sample": {
                "instrument": last[0],
                "decision": last[1],
                "timestamp": last[2],
            } if last else None,
        }

    def get_recent_ml_samples(self, limit: int = 24) -> list[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT ts, instrument, score, direction, spread, decision, confidence
                FROM ml_samples
                ORDER BY id DESC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()

        return [
            {
                "timestamp": row[0],
                "instrument": row[1],
                "score": float(row[2] or 0),
                "direction": row[3],
                "spread": float(row[4] or 0),
                "decision": row[5] or "WAIT",
                "confidence": float(row[6] or 0),
            }
            for row in rows[::-1]
        ]

    def get_ml_training_samples(self, limit: int = 1000) -> list[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT ts, instrument, score, direction, rsi, macd, spread, decision, confidence
                FROM ml_samples
                ORDER BY id DESC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()

        return [
            {
                "timestamp": row[0],
                "instrument": row[1],
                "score": float(row[2] or 0),
                "direction": row[3],
                "rsi": float(row[4] or 50),
                "macd": float(row[5] or 0),
                "spread": float(row[6] or 0),
                "decision": row[7] or "WAIT",
                "confidence": float(row[8] or 0),
            }
            for row in rows[::-1]
        ]

    def count_ml_samples_for(self, instrument: str, window: int = 220) -> int:
        """Count samples for an instrument within the ML training window (last N samples)."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM (SELECT instrument FROM ml_samples ORDER BY id DESC LIMIT ?) sub WHERE UPPER(instrument) = ?",
                (int(window), str(instrument).upper()),
            ).fetchone()
        return int(row[0] or 0) if row else 0
