"""
Backtest walk-forward : teste la stratégie XAUUSDm sur données historiques.
Reproduit fidèlement le comportement du bot live spécialisé Gold.

Usage:
    python backtest.py XAUUSDm 10
    python backtest.py XAUUSDm 20
    (teste sur N derniers jours)
"""

import sys
import math
from datetime import datetime, timezone
from typing import List, Dict, Optional

try:
    from mt5_bridge import build_broker
    from signal_engine import calculate_mtf_signal, calculate_signal_score
    from scalping_strategy import calculate_scalp_signal
    from learning_store import AgentMemory
    from runtime_db import RuntimeStore
    from settings import (
        INITIAL_CAPITAL,
        MAX_RISK_PER_TRADE,
        MAX_TRADES_PER_DAY,
        TRADE_COOLDOWN_MINUTES,
        STRATEGY_MODE,
        SCALP_TIMEFRAME,
        MAX_SPREAD_FILTER_GOLD,
    )
except ImportError as e:
    print(f"[BACKTEST] Import error: {e}")
    sys.exit(1)


def _parse_candle_time(candle: Dict) -> Optional[datetime]:
    """Parse le timestamp d'une bougie en datetime UTC."""
    raw = candle.get("time") or candle.get("timestamp") or ""
    if not raw:
        return None
    try:
        if isinstance(raw, (int, float)):
            return datetime.fromtimestamp(float(raw), tz=timezone.utc)
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


class SimpleBacktester:
    """Backtest léger reproduisant le comportement live du bot Exeness."""

    def __init__(self, broker, instrument: str = "XAUUSDm"):
        self.broker = broker
        self.instrument = instrument
        self.trades: List[Dict] = []
        self.balances: List[float] = [float(INITIAL_CAPITAL)]
        self.spread_pips: float = 1.5
        self.memory = AgentMemory()
        self.store = RuntimeStore()
        try:
            self.runtime_settings = self.store.get_settings()
        except Exception:
            self.runtime_settings = {}
        # Cooldown entre trades (Rule 5)
        self._last_trade_close_time: Optional[datetime] = None
        self.cooldown_minutes: int = int(TRADE_COOLDOWN_MINUTES)
        # Compteur journalier (Rule 8)
        self._trades_today: Dict[str, int] = {}

    def _classic_candidate(self, signal: Dict, signal_confirm: Optional[Dict]) -> Optional[Dict]:
        direction = signal.get("direction")
        score = int(signal.get("score", 0) or 0)
        if direction not in ("BUY", "SELL") or score < 3:
            return None

        confirm_ok = True
        if signal_confirm and isinstance(signal_confirm, dict):
            confirm_dir = signal_confirm.get("direction")
            confirm_score = int(signal_confirm.get("score", 0) or 0)
            confirm_ok = confirm_dir == direction and confirm_score >= max(2, score - 1)

        if not confirm_ok:
            return None

        return {
            "source": "classic",
            "direction": direction,
            "score": min(score, 5),
            "details": signal.get("details", {}) or {},
            "signal_confirm": signal_confirm,
        }

    def _scalp_candidate(self, scalp_signal: Dict) -> Optional[Dict]:
        direction = scalp_signal.get("signal")
        raw_score = int(scalp_signal.get("score", 0) or 0)
        if direction not in ("BUY", "SELL") or raw_score <= 0:
            return None

        sl_pips = float(scalp_signal.get("sl_pips", 0.0) or 0.0)
        tp_pips = float(scalp_signal.get("tp_pips", 0.0) or 0.0)
        rr = round(tp_pips / sl_pips, 2) if sl_pips > 0 else 0.0
        quality_score = round(min(1.0, max(0.35, raw_score / 6.0)), 2)
        details = dict(scalp_signal.get("details", {}) or {})
        details.update({
            "atr_pips": float(scalp_signal.get("atr_pips", 0.0) or 0.0),
            "quality_score": quality_score,
            "signal_source": "scalping",
            "scalp_mode": scalp_signal.get("mode", "momentum"),
            "scalp_reasons": scalp_signal.get("reasons", []),
            "distance_to_support_pips": sl_pips if direction == "BUY" else tp_pips,
            "distance_to_resistance_pips": tp_pips if direction == "BUY" else sl_pips,
            "rr_buy": rr if direction == "BUY" else 0.0,
            "rr_sell": rr if direction == "SELL" else 0.0,
        })
        return {
            "source": "scalping",
            "direction": direction,
            "score": min(raw_score, 5),
            "details": details,
            "signal_confirm": None,
        }

    def _select_candidate(self, classic: Optional[Dict], scalp: Optional[Dict]) -> Optional[Dict]:
        mode = str(self.runtime_settings.get("strategy_mode", STRATEGY_MODE)).strip().lower()
        if mode == "classic":
            return classic
        if mode == "scalping":
            return scalp
        if classic and scalp:
            if classic["direction"] != scalp["direction"]:
                return None
            merged_details = dict(classic.get("details", {}) or {})
            merged_details.update(scalp.get("details", {}) or {})
            merged_details["signal_source"] = "hybrid"
            return {
                "source": "hybrid",
                "direction": classic["direction"],
                "score": min(max(int(classic["score"]), int(scalp["score"])) + 1, 5),
                "details": merged_details,
                "signal_confirm": classic.get("signal_confirm"),
            }
        return classic or scalp

    def _live_volume(self, balance: float, sl_pips: float) -> float:
        risk_usd = float(balance) * float(MAX_RISK_PER_TRADE)
        pip_value_per_lot = 1.0
        lot = risk_usd / max(float(sl_pips) * pip_value_per_lot, 0.01)
        return max(0.01, min(0.50, round(lot / 0.01) * 0.01))

    # ── Données historiques ──────────────────────────────────────────────────

    def load_historical_data(self, days: int = 10) -> Dict[str, List[Dict]]:
        """Charge M5 + M15 + H1 + H4 + D1 pour reproduire le live hybride."""
        result: Dict[str, List[Dict]] = {"m5": [], "m15": [], "h1": [], "h4": [], "d1": []}
        scalp_tf = str(self.runtime_settings.get("scalp_timeframe", SCALP_TIMEFRAME)).strip().upper() or SCALP_TIMEFRAME
        if scalp_tf == "M5":
            try:
                result["m5"] = self.broker.get_candles(self.instrument, "M5", days * 24 * 12 + 100)
                print(f"[BACKTEST] M5:  {len(result['m5'])} candles")
            except Exception as e:
                print(f"[BACKTEST] Erreur M5 (non bloquant): {e}")
        try:
            result["m15"] = self.broker.get_candles(self.instrument, "M15", days * 96)
            print(f"[BACKTEST] M15: {len(result['m15'])} candles")
        except Exception as e:
            print(f"[BACKTEST] Erreur M15: {e}")

        try:
            result["h1"] = self.broker.get_candles(self.instrument, "H1", days * 24 + 50)
            print(f"[BACKTEST] H1:  {len(result['h1'])} candles")
        except Exception as e:
            print(f"[BACKTEST] Erreur H1 (non bloquant): {e}")

        try:
            result["d1"] = self.broker.get_candles(self.instrument, "D1", max(100, days + 50))
            print(f"[BACKTEST] D1:  {len(result['d1'])} candles")
        except Exception as e:
            print(f"[BACKTEST] Erreur D1 (non bloquant): {e}")

        try:
            result["h4"] = self.broker.get_candles(self.instrument, "H4", days * 6 + 60)
            print(f"[BACKTEST] H4:  {len(result['h4'])} candles")
        except Exception as e:
            print(f"[BACKTEST] Erreur H4 (non bloquant): {e}")

        return result

    # ── Helpers instrument ───────────────────────────────────────────────────

    def _pip_size(self) -> float:
        inst = self.instrument.upper()
        if "JPY" in inst:
            return 0.01
        if inst.startswith("XAU") or inst.startswith("XAG"):
            return 0.10
        if inst.startswith("BTC") or inst.startswith("ETH"):
            return 1.0
        return 0.0001

    def _pip_value_per_lot(self) -> float:
        inst = self.instrument.upper()
        if inst.startswith(("XAU", "XAG")):
            return 1.0
        if inst.startswith(("BTC", "ETH")):
            return 1.0
        return 10.0

    def _auto_spread(self) -> float:
        inst = self.instrument.upper()
        if inst.startswith("XAU") or inst.startswith("XAG"):
            return 3.0
        if inst.startswith("BTC") or inst.startswith("ETH"):
            return 50.0
        return 1.5

    # ── Session filter (Rule 7) ──────────────────────────────────────────────

    def _is_trading_session(self, candle_time: datetime) -> bool:
        """London 07-16 UTC + NY 13-21 UTC → 07-21 UTC."""
        return 7 <= candle_time.hour <= 21

    # ── Trade lifecycle ──────────────────────────────────────────────────────

    def _open_trade(self, direction: str, entry: float, sl: float, tp: float,
                    candle_time: datetime, size: float = 0.01):
        self.trades.append({
            "timestamp": candle_time.isoformat(),
            "instrument": self.instrument,
            "direction": direction,
            "entry": entry,
            "sl": sl,
            "tp": tp,
            "size": size,
            "status": "open",
            "pnl": 0.0,
        })
        date_key = candle_time.strftime("%Y-%m-%d")
        self._trades_today[date_key] = self._trades_today.get(date_key, 0) + 1

    def _check_sl_tp(self, candle: Dict) -> Optional[Dict]:
        """Vérifie si le trade ouvert touche SL ou TP sur cette bougie."""
        if not self.trades:
            return None
        trade = self.trades[-1]
        if trade["status"] != "open":
            return None

        low = float(candle.get("low", candle.get("close", 0)))
        high = float(candle.get("high", candle.get("close", 0)))
        close = float(candle.get("close", 0))
        candle_time = _parse_candle_time(candle)

        if trade["direction"] == "BUY":
            if low <= trade["sl"]:
                return self._close_trade(trade, trade["sl"], "SL hit", candle_time)
            if high >= trade["tp"]:
                return self._close_trade(trade, trade["tp"], "TP hit", candle_time)
        else:
            if high >= trade["sl"]:
                return self._close_trade(trade, trade["sl"], "SL hit", candle_time)
            if low <= trade["tp"]:
                return self._close_trade(trade, trade["tp"], "TP hit", candle_time)
        return None

    def _close_trade(self, trade: Dict, exit_price: float, reason: str,
                     close_time: Optional[datetime]) -> Dict:
        pip = self._pip_size()
        pv_per_lot = self._pip_value_per_lot()
        pip_value = pv_per_lot * trade["size"]

        if trade["direction"] == "BUY":
            pips_move = (exit_price - trade["entry"]) / pip
        else:
            pips_move = (trade["entry"] - exit_price) / pip

        spread_cost = self.spread_pips * pip_value
        pnl = pips_move * pip_value - spread_cost

        trade["status"] = "closed"
        trade["exit_price"] = exit_price
        trade["close_reason"] = reason
        trade["spread_pips"] = self.spread_pips
        trade["spread_cost"] = round(spread_cost, 4)
        trade["pnl"] = round(pnl, 4)
        trade["closed_at"] = close_time.isoformat() if close_time else ""

        self.balances.append(self.balances[-1] + pnl)
        self._last_trade_close_time = close_time
        return trade

    # ── Main backtest loop ───────────────────────────────────────────────────

    def run_backtest(self, days: int = 10) -> Dict:
        """Exécute le backtest sur N jours (M15, filtres live)."""
        self.spread_pips = self._auto_spread()
        print(f"\n[BACKTEST] {self.instrument} | {days} jours | spread={self.spread_pips}p")

        data = self.load_historical_data(days)
        strategy_mode = str(self.runtime_settings.get("strategy_mode", STRATEGY_MODE)).strip().lower()
        candles_m15 = data["m15"]
        candles_m5 = data["m5"]
        candles_h1 = data["h1"]
        candles_h4 = data["h4"]
        candles_d1 = data["d1"]

        if len(candles_m15) < 60:
            print(f"[BACKTEST] Données M15 insuffisantes: {len(candles_m15)} < 60")
            return self._compute_stats(days)

        win_m15: List[Dict] = []
        win_m5: List[Dict] = []
        win_h1: List[Dict] = []
        win_h4: List[Dict] = []

        # Index H1 par position approximative (chaque M15 → avance dans H1)
        h1_cursor = 0
        h4_cursor = 0
        m5_cursor = 0

        for i, candle in enumerate(candles_m15):
            candle_time = _parse_candle_time(candle)

            # Avancer le curseur H1 au temps correspondant
            if candles_h1 and candle_time:
                while h1_cursor + 1 < len(candles_h1):
                    next_h1_time = _parse_candle_time(candles_h1[h1_cursor + 1])
                    if next_h1_time and next_h1_time <= candle_time:
                        h1_cursor += 1
                    else:
                        break
                win_h1 = candles_h1[:h1_cursor + 1][-100:]

            if candles_h4 and candle_time:
                while h4_cursor + 1 < len(candles_h4):
                    next_h4_time = _parse_candle_time(candles_h4[h4_cursor + 1])
                    if next_h4_time and next_h4_time <= candle_time:
                        h4_cursor += 1
                    else:
                        break
                win_h4 = candles_h4[:h4_cursor + 1][-60:]

            if candles_m5 and candle_time:
                while m5_cursor + 1 < len(candles_m5):
                    next_m5_time = _parse_candle_time(candles_m5[m5_cursor + 1])
                    if next_m5_time and next_m5_time <= candle_time:
                        m5_cursor += 1
                    else:
                        break
                win_m5 = candles_m5[:m5_cursor + 1][-100:]

            win_m15.append(candle)
            if len(win_m15) > 200:
                win_m15 = win_m15[-200:]

            # Check SL/TP sur le trade en cours
            self._check_sl_tp(candle)

            # Warmup: minimum 60 bougies avant tout signal
            if len(win_m15) < 60:
                continue

            # Pas de nouveau trade si un est déjà ouvert
            open_trades = [t for t in self.trades if t["status"] == "open"]
            if open_trades:
                continue

            # Rule 7 — filtre session London/NY
            if candle_time and not self._is_trading_session(candle_time):
                continue

            # Cooldown live
            if candle_time and self._last_trade_close_time is not None:
                elapsed = (candle_time - self._last_trade_close_time).total_seconds() / 60
                if elapsed < self.cooldown_minutes:
                    continue

            # Limite journalière live
            if candle_time:
                date_key = candle_time.strftime("%Y-%m-%d")
                if self._trades_today.get(date_key, 0) >= int(MAX_TRADES_PER_DAY):
                    continue

            # Signal live: H1+D1 (classic) + M15 confirm + M5 scalp
            try:
                spread = float(self.spread_pips)
                classic_signal = calculate_mtf_signal(win_h1, candles_d1, self.instrument, candles_h4=win_h4) if len(win_h1) >= 20 else {}
                signal_confirm = calculate_signal_score(win_m15, self.instrument) if len(win_m15) >= 20 else None
                scalp_signal = None
                if strategy_mode in {"scalping", "hybrid"} and len(win_m5) >= 30:
                    scalp_signal = calculate_scalp_signal(
                        win_m5,
                        instrument=self.instrument,
                        spread_pips=spread,
                        config=self.runtime_settings,
                    )
                signal = self._select_candidate(
                    self._classic_candidate(classic_signal or {}, signal_confirm),
                    self._scalp_candidate(scalp_signal or {}),
                ) or {}
            except Exception:
                try:
                    signal = self._classic_candidate(calculate_signal_score(win_m15, self.instrument), None) or {}
                except Exception:
                    continue

            direction = signal.get("direction")
            score = int(signal.get("score", 0) or 0)
            details = signal.get("details", {}) or {}
            adx = float(details.get("adx", 0) or 0)
            quality = float(details.get("quality_score", 0) or 0)

            # Filtres live risk/routing
            if not direction or direction == "WAIT":
                continue
            rr_key = "rr_buy" if direction == "BUY" else "rr_sell"
            rr = float(details.get(rr_key, 0.0) or 0.0)
            if spread > float(MAX_SPREAD_FILTER_GOLD):
                continue
            if score < 3 or adx < 18 or quality < 0.35 or (0 < rr < 1.5):
                continue

            # Ouvrir le trade
            entry = float(candle.get("close", 0))
            if entry <= 0:
                continue

            atr_pips = float(details.get("atr_pips", 20) or 20)
            pip = self._pip_size()
            if direction == "BUY":
                sl_pips = int(details.get("distance_to_support_pips", atr_pips * 1.5))
                tp_pips = int(details.get("distance_to_resistance_pips", atr_pips * 3.0))
            else:
                sl_pips = int(details.get("distance_to_resistance_pips", atr_pips * 1.5))
                tp_pips = int(details.get("distance_to_support_pips", atr_pips * 3.0))
            sl_pips = max(sl_pips, max(15, int(atr_pips * 1.0)))
            tp_pips = max(tp_pips, sl_pips * 2)

            if direction == "BUY":
                sl = entry - sl_pips * pip
                tp = entry + tp_pips * pip
            else:
                sl = entry + sl_pips * pip
                tp = entry - tp_pips * pip

            size = self._live_volume(self.balances[-1], sl_pips)
            self._open_trade(direction, entry, sl, tp, candle_time or datetime.now(timezone.utc), size=size)

        # Fermer tout trade encore ouvert sur le dernier close
        if self.trades and self.trades[-1]["status"] == "open" and candles_m15:
            last = candles_m15[-1]
            last_time = _parse_candle_time(last)
            self._close_trade(self.trades[-1], float(last.get("close", 0)),
                              "end_of_data", last_time)

        return self._compute_stats(days)

    # ── Statistiques ─────────────────────────────────────────────────────────

    def _compute_stats(self, days: int = 10) -> Dict:
        closed_trades = [t for t in self.trades if t["status"] == "closed"]

        if not closed_trades:
            return {
                "instrument": self.instrument,
                "days": days,
                "total_trades": len(self.trades),
                "closed_trades": 0,
                "win_rate": 0.0,
                "total_pnl": 0.0,
                "avg_pnl_per_trade": 0.0,
                "max_drawdown": 0.0,
                "sharpe_ratio": 0.0,
                "profit_factor": 0.0,
                "trades_per_day": 0.0,
                "best_trade": 0.0,
                "worst_trade": 0.0,
                "final_balance": round(self.balances[-1], 2),
            }

        pnls = [t["pnl"] for t in closed_trades]
        wins = sum(1 for p in pnls if p > 0)
        win_rate = wins / len(pnls)
        total_pnl = sum(pnls)
        avg_pnl = total_pnl / len(pnls)

        gross_profit = sum(p for p in pnls if p > 0)
        gross_loss = abs(sum(p for p in pnls if p < 0))
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (float("inf") if gross_profit > 0 else 0.0)

        variance = sum((p - avg_pnl) ** 2 for p in pnls) / len(pnls)
        std_dev = math.sqrt(variance)
        sharpe_ratio = (avg_pnl / std_dev) * math.sqrt(len(pnls)) if std_dev > 0 else 0.0

        max_drawdown = 0.0
        peak = self.balances[0]
        for b in self.balances:
            if b > peak:
                peak = b
            dd = (peak - b) / peak if peak > 0 else 0.0
            if dd > max_drawdown:
                max_drawdown = dd

        return {
            "instrument": self.instrument,
            "days": days,
            "total_trades": len(self.trades),
            "closed_trades": len(closed_trades),
            "win_rate": round(win_rate, 3),
            "total_pnl": round(total_pnl, 2),
            "avg_pnl_per_trade": round(avg_pnl, 2),
            "max_drawdown": round(max_drawdown, 3),
            "sharpe_ratio": round(sharpe_ratio, 3),
            "profit_factor": round(profit_factor, 3) if math.isfinite(profit_factor) else float("inf"),
            "trades_per_day": round(len(closed_trades) / max(days, 1), 2),
            "best_trade": round(max(pnls), 2),
            "worst_trade": round(min(pnls), 2),
            "final_balance": round(self.balances[-1], 2),
            "trades_sample": closed_trades[:5],
        }


# ── CLI ───────────────────────────────────────────────────────────────────────

def run_backtest_cli():
    instrument = sys.argv[1] if len(sys.argv) > 1 else "XAUUSDm"
    days = int(sys.argv[2]) if len(sys.argv) > 2 else 10

    try:
        broker = build_broker()
        bt = SimpleBacktester(broker, instrument)
        stats = bt.run_backtest(days)

        print("\n" + "=" * 60)
        print(f"  BACKTEST RESULTS — {instrument} ({days} jours)")
        print("=" * 60)
        print(f"  Total trades:   {stats.get('total_trades', 0)}")
        print(f"  Closed trades:  {stats.get('closed_trades', 0)}")
        print(f"  Win rate:       {stats.get('win_rate', 0):.1%}")
        print(f"  Total P&L:      ${stats.get('total_pnl', 0):.2f}")
        print(f"  Avg P&L/trade:  ${stats.get('avg_pnl_per_trade', 0):.2f}")
        print(f"  Best trade:     ${stats.get('best_trade', 0):.2f}")
        print(f"  Worst trade:    ${stats.get('worst_trade', 0):.2f}")
        print(f"  Max drawdown:   {stats.get('max_drawdown', 0):.1%}")
        print(f"  Profit factor:  {stats.get('profit_factor', 0):.2f}")
        print(f"  Sharpe ratio:   {stats.get('sharpe_ratio', 0):.2f}")
        print(f"  Trades/day:     {stats.get('trades_per_day', 0):.1f}")
        print(f"  Final balance:  ${stats.get('final_balance', 1000):.2f}")
        print("=" * 60 + "\n")

        return stats
    except Exception as e:
        print(f"[BACKTEST] Erreur: {e}")
        import traceback
        traceback.print_exc()
        return {"error": str(e)}


if __name__ == "__main__":
    run_backtest_cli()
