"""
Filtre de qualité des signaux pour bloquer les setups contradictoires ou trop faibles.
"""

from datetime import datetime, timedelta, timezone
from typing import Dict, Optional


def _parse_iso_date(timestamp: str) -> Optional[datetime]:
    if not timestamp:
        return None
    try:
        return datetime.fromisoformat(timestamp)
    except Exception:
        try:
            return datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%S")
        except Exception:
            return None


def get_recent_trades_count(memory, minutes: int = 30) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    count = 0
    for trade in getattr(memory, "trades", []):
        ts = trade.get("timestamp", "")
        dt = _parse_iso_date(ts)
        if dt and dt >= cutoff:
            count += 1
    return count


def filter_signal_quality(
    signal: Dict,
    signal_confirm: Optional[Dict],
    market_context: Dict,
    open_positions: int,
    memory,
    config: Dict,
) -> Dict:
    result = {
        "blocked": False,
        "reason": "",
        "details": [],
    }

    if not signal or signal.get("direction") not in ("BUY", "SELL"):
        result["blocked"] = True
        result["reason"] = "Signal absent ou direction invalide"
        return result

    score = int(signal.get("score", 0) or 0)
    bias = abs(float(signal.get("details", {}).get("signal_bias", 0) or 0))
    category = market_context.get("category", "unknown")

    if score < config["min_signal_score"]:
        result["blocked"] = True
        result["details"].append(f"score trop faible ({score} < {config['min_signal_score']})")

    if signal_confirm and signal_confirm.get("direction") and signal_confirm.get("direction") != signal.get("direction"):
        if int(signal_confirm.get("score", 0) or 0) >= 2:
            result["blocked"] = True
            result["details"].append("conflit entre timeframes")

    if bias < config["min_signal_bias"] and score < 4:
        result["details"].append("biais du signal faible")
        if category == "uncertain":
            result["blocked"] = True
            result["details"].append("marché indécis et biais insuffisant")

    if category == "range" and score < 4:
        result["blocked"] = True
        result["details"].append("range sans confirmation suffisante")

    if category == "trend" and score < 3:
        result["details"].append("trend confirmé mais score faible")

    if open_positions >= config["max_open_positions"]:
        result["blocked"] = True
        result["details"].append("nombre maximal de positions ouvertes atteint")

    trades_today = memory.get_trades_started_today() if hasattr(memory, "get_trades_started_today") else 0
    if trades_today >= config["max_trades_per_day"]:
        result["blocked"] = True
        result["details"].append(f"plafond de trades journaliers atteint ({trades_today})")

    recent_trades = get_recent_trades_count(memory, minutes=config["trade_cooldown_minutes"])
    if recent_trades >= 2:
        result["blocked"] = True
        result["details"].append(
            f"cooldown actif: {recent_trades} trades dans les {config['trade_cooldown_minutes']} dernières minutes"
        )

    result["reason"] = "; ".join(result["details"]) if result["details"] else "qualité satisfaisante"
    return result
