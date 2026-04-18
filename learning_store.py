"""
Mémoire persistante locale.
Apprentissage des trades, des horaires, des patterns et du budget LLM local.
"""

import json
import os
from datetime import datetime, timezone
from typing import Dict, List
from settings import MEMORY_FILE, TRADES_FILE, DAILY_TOKEN_BUDGET


class AgentMemory:
    def __init__(self):
        self.memory_file = MEMORY_FILE
        self.trades_file = TRADES_FILE
        os.makedirs(os.path.dirname(self.memory_file), exist_ok=True)
        self.memory = self._load_memory()
        self.trades = self._load_trades()
        self._migrate_legacy_keys()

    def _safe_load_json(self, path, fallback):
        if not os.path.exists(path):
            return fallback
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return fallback

    def _load_memory(self) -> Dict:
        return self._safe_load_json(self.memory_file, {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "total_pnl": 0.0,
            "daily_pnl": {},
            "llm_calls_today": 0,
            "llm_calls_date": "",
            "token_usage": {"date": "", "prompt_tokens": 0, "completion_tokens": 0},
            "pattern_stats": {},
            "instrument_stats": {},
            "hour_stats": {},
            "learned_filters": [],
            "last_ai_insights": [],
            "session_log": [],
            "error_log": [],
        })

    def _migrate_legacy_keys(self):
        if "api_calls_today" in self.memory and "llm_calls_today" not in self.memory:
            self.memory["llm_calls_today"] = int(self.memory.get("api_calls_today", 0))
        if "api_calls_date" in self.memory and "llm_calls_date" not in self.memory:
            self.memory["llm_calls_date"] = self.memory.get("api_calls_date", "")
        if "last_claude_insights" in self.memory and "last_ai_insights" not in self.memory:
            self.memory["last_ai_insights"] = list(self.memory.get("last_claude_insights", []))
        self.save()

    def _load_trades(self) -> List:
        return self._safe_load_json(self.trades_file, [])

    def save(self):
        os.makedirs(os.path.dirname(self.memory_file), exist_ok=True)
        with open(self.memory_file, "w", encoding="utf-8") as f:
            json.dump(self.memory, f, indent=2, ensure_ascii=False)
        with open(self.trades_file, "w", encoding="utf-8") as f:
            json.dump(self.trades, f, indent=2, ensure_ascii=False)

    # === LLM / TOKEN BUDGET ===
    def increment_llm_calls(self) -> int:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self.memory.get("llm_calls_date") != today:
            self.memory["llm_calls_today"] = 0
            self.memory["llm_calls_date"] = today
        self.memory["llm_calls_today"] += 1
        self.save()
        return self.memory["llm_calls_today"]

    def get_llm_calls_today(self) -> int:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self.memory.get("llm_calls_date") != today:
            return 0
        return int(self.memory.get("llm_calls_today", 0))

    def record_token_usage(self, prompt_tokens: int = 0, completion_tokens: int = 0):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        usage = self.memory.setdefault("token_usage", {"date": today, "prompt_tokens": 0, "completion_tokens": 0})
        if usage.get("date") != today:
            usage["date"] = today
            usage["prompt_tokens"] = 0
            usage["completion_tokens"] = 0
        usage["prompt_tokens"] += int(prompt_tokens)
        usage["completion_tokens"] += int(completion_tokens)
        self.save()

    def get_token_usage_today(self) -> Dict:
        usage = self.memory.get("token_usage", {})
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if usage.get("date") != today:
            return {"date": today, "prompt_tokens": 0, "completion_tokens": 0, "budget": DAILY_TOKEN_BUDGET}
        return {
            "date": today,
            "prompt_tokens": int(usage.get("prompt_tokens", 0)),
            "completion_tokens": int(usage.get("completion_tokens", 0)),
            "budget": DAILY_TOKEN_BUDGET,
        }

    # === FEEDBACK / ERREURS ===
    def record_error(self, source: str, message: str):
        entry = f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}] {source}: {message}"
        self.memory.setdefault("error_log", []).append(entry)
        self.memory["error_log"] = self.memory["error_log"][-50:]
        self.save()

    def assess_setup(self, instrument: str, signal: Dict) -> Dict:
        reasons = []
        risk_multiplier = 1.0
        pattern = signal.get("pattern", "unknown")

        pattern_stats = self.memory.get("pattern_stats", {}).get(pattern, {})
        if pattern_stats.get("trades", 0) >= 3:
            win_rate = (pattern_stats.get("wins", 0) / pattern_stats.get("trades", 1)) * 100
            if win_rate < 35 or pattern_stats.get("total_pnl", 0) < 0:
                reasons.append(f"pattern fragile ({win_rate:.0f}% WR)")
                risk_multiplier *= 0.65

        inst_stats = self.memory.get("instrument_stats", {}).get(instrument, {})
        if inst_stats.get("trades", 0) >= 4 and inst_stats.get("total_pnl", 0) < 0:
            reasons.append("instrument en sous-performance")
            risk_multiplier *= 0.75

        hour_stats = self.memory.get("hour_stats", {}).get(str(datetime.now(timezone.utc).hour), {})
        if hour_stats.get("trades", 0) >= 4:
            win_rate = (hour_stats.get("wins", 0) / hour_stats.get("trades", 1)) * 100
            if win_rate < 35:
                reasons.append("créneau horaire faible")
                risk_multiplier *= 0.8

        blocked = risk_multiplier <= 0.45
        return {
            "blocked": blocked,
            "risk_multiplier": round(max(0.25, risk_multiplier), 2),
            "reasons": reasons,
        }

    # === GESTION DES TRADES ===
    def add_trade(self, trade: Dict):
        trade["id"] = len(self.trades) + 1
        trade["timestamp"] = datetime.now(timezone.utc).isoformat()
        self.trades.append(trade)
        self._update_stats(trade)
        self.save()
        return trade["id"]

    def update_trade(self, trade_id: int, update: Dict):
        for trade in self.trades:
            if trade.get("id") == trade_id:
                trade.update(update)
                if "pnl" in update:
                    self._finalize_trade_stats(trade)
                self.save()
                return trade
        return None

    def _update_stats(self, trade: Dict):
        instrument = trade.get("instrument", "unknown")
        if instrument not in self.memory["instrument_stats"]:
            self.memory["instrument_stats"][instrument] = {"trades": 0, "wins": 0, "total_pnl": 0.0}
        self.memory["instrument_stats"][instrument]["trades"] += 1
        self.memory["total_trades"] += 1

        hour_key = str(datetime.now(timezone.utc).hour)
        if hour_key not in self.memory["hour_stats"]:
            self.memory["hour_stats"][hour_key] = {"trades": 0, "wins": 0, "total_pnl": 0.0}
        self.memory["hour_stats"][hour_key]["trades"] += 1

    def _finalize_trade_stats(self, trade: Dict):
        pnl = float(trade.get("pnl", 0))
        instrument = trade.get("instrument", "unknown")
        pattern = trade.get("pattern", "unknown")
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Guard: avoid double-counting if stats already finalized for this trade
        if trade.get("_stats_finalized"):
            return
        trade["_stats_finalized"] = True

        self.memory["total_pnl"] += pnl
        self.memory["daily_pnl"][today] = self.memory["daily_pnl"].get(today, 0.0) + pnl

        if pnl > 0:
            self.memory["winning_trades"] += 1
            self.memory["instrument_stats"].setdefault(instrument, {"trades": 0, "wins": 0, "total_pnl": 0.0})
            self.memory["instrument_stats"][instrument]["wins"] += 1
        else:
            self.memory["losing_trades"] += 1
            self.record_error("trade", f"Perte sur {instrument} / {pattern}: ${pnl:.2f}")

        self.memory["instrument_stats"].setdefault(instrument, {"trades": 0, "wins": 0, "total_pnl": 0.0})
        self.memory["instrument_stats"][instrument]["total_pnl"] += pnl

        self.memory["pattern_stats"].setdefault(pattern, {"trades": 0, "wins": 0, "total_pnl": 0.0})
        self.memory["pattern_stats"][pattern]["trades"] += 1
        self.memory["pattern_stats"][pattern]["total_pnl"] += pnl
        if pnl > 0:
            self.memory["pattern_stats"][pattern]["wins"] += 1

        self._refresh_learned_filters()

    def _refresh_learned_filters(self):
        learned = []
        for name, stats in self.memory.get("pattern_stats", {}).items():
            trades = stats.get("trades", 0)
            if trades >= 3:
                wr = (stats.get("wins", 0) / trades) * 100
                if wr < 35 or stats.get("total_pnl", 0) < 0:
                    learned.append(f"éviter pattern {name} (WR {wr:.0f}%)")
        self.memory["learned_filters"] = learned[-20:]

    def rebuild_stats_from_trades(self):
        """Recalculate all stats from the trade list. Fixes any corruption."""
        self.memory["total_trades"] = 0
        self.memory["winning_trades"] = 0
        self.memory["losing_trades"] = 0
        self.memory["total_pnl"] = 0.0
        self.memory["daily_pnl"] = {}
        self.memory["pattern_stats"] = {}
        self.memory["instrument_stats"] = {}
        self.memory["hour_stats"] = {}

        for trade in self.trades:
            instrument = trade.get("instrument", "unknown")
            pattern = trade.get("pattern", "unknown")
            self.memory["total_trades"] += 1

            self.memory["instrument_stats"].setdefault(instrument, {"trades": 0, "wins": 0, "total_pnl": 0.0})
            self.memory["instrument_stats"][instrument]["trades"] += 1

            ts = trade.get("timestamp", "")
            hour_key = ts[11:13] if len(ts) > 13 else "0"
            self.memory["hour_stats"].setdefault(hour_key, {"trades": 0, "wins": 0, "total_pnl": 0.0})
            self.memory["hour_stats"][hour_key]["trades"] += 1

            if trade.get("status") == "closed" and "pnl" in trade:
                pnl = float(trade["pnl"])
                day = (trade.get("closed_at") or trade.get("timestamp", ""))[:10]
                if day:
                    self.memory["daily_pnl"][day] = self.memory["daily_pnl"].get(day, 0.0) + pnl
                self.memory["total_pnl"] += pnl

                if pnl > 0:
                    self.memory["winning_trades"] += 1
                    self.memory["instrument_stats"][instrument]["wins"] += 1
                    self.memory["hour_stats"][hour_key]["wins"] += 1
                else:
                    self.memory["losing_trades"] += 1

                self.memory["instrument_stats"][instrument]["total_pnl"] += pnl
                self.memory["hour_stats"][hour_key]["total_pnl"] += pnl

                self.memory["pattern_stats"].setdefault(pattern, {"trades": 0, "wins": 0, "total_pnl": 0.0})
                self.memory["pattern_stats"][pattern]["trades"] += 1
                self.memory["pattern_stats"][pattern]["total_pnl"] += pnl
                if pnl > 0:
                    self.memory["pattern_stats"][pattern]["wins"] += 1

                trade["_stats_finalized"] = True

        self._refresh_learned_filters()
        self.save()

    # === STATS UTILES ===
    def get_daily_pnl(self, date: str = None) -> float:
        if date is None:
            date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return float(self.memory.get("daily_pnl", {}).get(date, 0.0))

    def get_win_rate(self) -> float:
        total = self.memory.get("total_trades", 0)
        if total == 0:
            return 0.0
        return (self.memory.get("winning_trades", 0) / total) * 100

    def get_best_patterns(self) -> List[Dict]:
        patterns = []
        for name, stats in self.memory.get("pattern_stats", {}).items():
            trades = stats.get("trades", 0)
            if trades >= 1:
                wr = (stats.get("wins", 0) / max(1, trades)) * 100
                patterns.append({"pattern": name, "win_rate": wr, **stats})
        return sorted(patterns, key=lambda x: (x["win_rate"], x.get("total_pnl", 0)), reverse=True)

    def get_best_hours(self) -> List[Dict]:
        hours = []
        for hour, stats in self.memory.get("hour_stats", {}).items():
            trades = stats.get("trades", 0)
            if trades >= 1:
                wr = (stats.get("wins", 0) / max(1, trades)) * 100
                hours.append({"hour": int(hour), "win_rate": wr, **stats})
        return sorted(hours, key=lambda x: (x["win_rate"], x.get("total_pnl", 0)), reverse=True)

    def get_recent_trades(self, n: int = 10) -> List[Dict]:
        return self.trades[-n:]

    def get_context_for_llm(self) -> str:
        recent = self.get_recent_trades(5)
        best_patterns = self.get_best_patterns()[:3]
        best_hours = self.get_best_hours()[:3]
        today_pnl = self.get_daily_pnl()
        win_rate = self.get_win_rate()
        token_usage = self.get_token_usage_today()
        filters = self.memory.get("learned_filters", [])[-5:]
        insights = self.memory.get("last_ai_insights", [])[-5:]

        return f"""
=== MÉMOIRE LOCALE AGENT ===
Total trades: {self.memory.get('total_trades', 0)}
Win rate global: {win_rate:.1f}%
P&L total: ${self.memory.get('total_pnl', 0.0):.2f}
P&L aujourd'hui: ${today_pnl:.2f}
Appels LLM aujourd'hui: {self.get_llm_calls_today()}
Budget tokens utilisé: {token_usage['prompt_tokens'] + token_usage['completion_tokens']} / {token_usage['budget']}

Meilleurs patterns:
{json.dumps(best_patterns, indent=2, ensure_ascii=False) if best_patterns else 'Pas encore assez de données'}

Meilleures heures:
{json.dumps(best_hours, indent=2, ensure_ascii=False) if best_hours else 'Pas encore assez de données'}

Filtres appris:
{chr(10).join(filters) if filters else 'Aucun filtre bloquant pour le moment'}

Insights IA précédents:
{chr(10).join(insights) if insights else 'Première analyse'}

Derniers trades:
{json.dumps(recent, indent=2, ensure_ascii=False) if recent else 'Aucun trade encore'}
"""

    def add_ai_insight(self, insight: str):
        self.memory.setdefault("last_ai_insights", []).append(
            f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}] {insight}"
        )
        self.memory["last_ai_insights"] = self.memory["last_ai_insights"][-20:]
        self.save()

    def log_session(self, message: str):
        entry = f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {message}"
        self.memory.setdefault("session_log", []).append(entry)
        self.memory["session_log"] = self.memory["session_log"][-300:]
        try:
            print(entry)
        except UnicodeEncodeError:
            print(entry.encode("ascii", errors="replace").decode("ascii"))
        self.save()
