"""
Backtest walk-forward simple : teste le stratégie sur données historiques.
Charge les derniers N jours, simule cycle par cycle, mesure performance.

Usage:
    python backtest.py EURUSD 10
    (teste sur 10 derniers jours)
"""

import sys
import json
import math
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Tuple, Optional
from pathlib import Path

try:
    from mt5_bridge import build_broker
    from signal_engine import calculate_signal_score
    from smart_strategies import build_strategies_context
    from learning_store import AgentMemory
    from runtime_db import RuntimeStore
except ImportError as e:
    print(f"[BACKTEST] Import error: {e}")
    sys.exit(1)


class SimpleBacktester:
    """Backtest léger sans OptimEngine, juste les équations de base."""

    def __init__(self, broker, instrument: str = "EURUSDm"):
        self.broker = broker
        self.instrument = instrument
        self.trades = []
        self.balances = [1000.0]
        self.spread_pips = 2.0
        self.memory = AgentMemory()
        self.store = RuntimeStore()

    def load_historical_data(self, days: int = 10) -> List[Dict]:
        """Charge les N derniers jours de M1."""
        try:
            candles = self.broker.get_candles(self.instrument, "M1", days * 1440)
            return candles[-days*1440:] if len(candles) >= days*1440 else candles
        except Exception as e:
            print(f"[BACKTEST] Erreur chargement données: {e}")
            return []

    def simulate_candle(self, candle: Dict, prev_candle: Optional[Dict] = None) -> Optional[Dict]:
        """Simule un candle individuel (simplifié)."""
        try:
            close = float(candle.get("close", 0))
            pip = self._pip_size()
            
            # Si un trade est ouvert, check SL/TP
            if self.trades:
                trade = self.trades[-1]
                if trade["status"] == "open":
                    if trade["direction"] == "BUY":
                        if close <= trade["sl"]:
                            return self._close_trade(trade, trade["sl"], "SL hit")
                        if close >= trade["tp"]:
                            return self._close_trade(trade, trade["tp"], "TP hit")
                    else:  # SELL
                        if close >= trade["sl"]:
                            return self._close_trade(trade, trade["sl"], "SL hit")
                        if close <= trade["tp"]:
                            return self._close_trade(trade, trade["tp"], "TP hit")
            
            return None
        except Exception as e:
            print(f"[BACKTEST] Erreur sim candle: {e}")
            return None

    def _open_trade(self, direction: str, entry: float, sl: float, tp: float, size: float = 0.01):
        """Ouvre un trade."""
        self.trades.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "instrument": self.instrument,
            "direction": direction,
            "entry": entry,
            "sl": sl,
            "tp": tp,
            "size": size,
            "status": "open",
            "pnl": 0.0,
        })

    def _close_trade(self, trade: Dict, exit_price: float, reason: str) -> Dict:
        """Ferme un trade et calcule P&L."""
        pip = self._pip_size()
        if trade["direction"] == "BUY":
            pips_move = (exit_price - trade["entry"]) / pip
        else:
            pips_move = (trade["entry"] - exit_price) / pip

        pip_value = 10.0 * trade["size"]
        if "XAU" in self.instrument or "BTC" in self.instrument:
            pip_value = 1.0 * trade["size"]
        pnl = pips_move * pip_value
        pnl -= self.spread_pips * pip_value * self._pip_size()  # coût du spread
        
        trade["status"] = "closed"
        trade["exit_price"] = exit_price
        trade["spread_pips"] = self.spread_pips
        trade["spread_cost"] = round(self.spread_pips * pip_value * self._pip_size(), 4)
        trade["pnl"] = pnl
        trade["close_reason"] = reason
        
        current_balance = self.balances[-1] + pnl
        self.balances.append(current_balance)
        
        return trade

    def _pip_size(self) -> float:
        if "JPY" in self.instrument:
            return 0.01
        if "XAU" in self.instrument:
            return 0.10
        if "BTC" in self.instrument:
            return 1.0
        return 0.0001

    def _pip_value_per_lot(self) -> float:
        """Approximation de valeur de pip selon l'instrument."""
        pip = self._pip_size()
        if pip >= 1.0:   # BTC, ETH...
            return 1.0
        if pip >= 0.1:   # XAU, XAG...
            return 1.0
        return 10.0      # Forex standards (incl. JPY)

    def run_backtest(self, days: int = 10, spread_pips: float = 2.0, score_threshold: int = 3) -> Dict:
        """Exécute le backtest sur N jours."""
        print(f"\n[BACKTEST] Démarrage sur {self.instrument} ({days} jours)")

        self.spread_pips = float(spread_pips)
        candles = self.load_historical_data(days)
        if not candles:
            print("[BACKTEST] Aucune donnée chargée")
            return {"error": "no_data"}

        print(f"[BACKTEST] Données chargées: {len(candles)} candles")

        min_window = 60
        if len(candles) < min_window:
            print(f"[BACKTEST] Données insuffisantes: {len(candles)} < {min_window}")
            return self._compute_stats()

        window = []
        for i, candle in enumerate(candles):
            window.append(candle)
            if len(window) < 60:
                continue
            if len(window) > 200:
                window = window[-200:]

            self.simulate_candle(candle, candles[i - 1] if i > 0 else None)

            open_trades = [t for t in self.trades if t["status"] == "open"]
            if not open_trades:
                signal = calculate_signal_score(window, self.instrument)
                direction = signal.get("direction")
                score = signal.get("score", 0)
                if direction and score >= 3:
                    entry = float(candle["close"])
                    atr_pips = signal.get("details", {}).get("atr_pips", 20)
                    pip = self._pip_size()
                    if direction == "BUY":
                        sl = entry - atr_pips * pip * 1.5
                        tp = entry + atr_pips * pip * 3.0
                    else:
                        sl = entry + atr_pips * pip * 1.5
                        tp = entry - atr_pips * pip * 3.0
                    self._open_trade(direction, entry, sl, tp)
        
        return self._compute_stats()

    def _compute_stats(self) -> Dict:
        """Calcule les statistiques du backtest."""
        closed_trades = [t for t in self.trades if t["status"] == "closed"]
        
        if not closed_trades:
            return {
                "instrument": self.instrument,
                "total_trades": len(self.trades),
                "closed_trades": 0,
                "win_rate": 0.0,
                "total_pnl": 0.0,
                "max_drawdown": 0.0,
                "sharpe_ratio": 0.0,
                "profit_factor": 0.0,
            }
        
        pnls = [t["pnl"] for t in closed_trades]
        wins = sum(1 for p in pnls if p > 0)
        win_rate = wins / len(pnls) if pnls else 0.0
        total_pnl = sum(pnls)

        gross_profit = sum(p for p in pnls if p > 0)
        gross_loss = abs(sum(p for p in pnls if p < 0))
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (float("inf") if gross_profit > 0 else 0.0)

        avg_pnl = total_pnl / len(pnls) if pnls else 0.0
        variance = sum((p - avg_pnl) ** 2 for p in pnls) / len(pnls) if pnls else 0.0
        std_dev = math.sqrt(variance)
        sharpe_ratio = (avg_pnl / std_dev) * math.sqrt(len(pnls)) if std_dev > 0 else 0.0
        
        # Max drawdown
        max_drawdown = 0.0
        peak = self.balances[0]
        for balance in self.balances:
            if balance > peak:
                peak = balance
            drawdown = (peak - balance) / peak if peak > 0 else 0
            if drawdown > max_drawdown:
                max_drawdown = drawdown
        
        return {
            "instrument": self.instrument,
            "total_trades": len(self.trades),
            "closed_trades": len(closed_trades),
            "win_rate": round(win_rate, 3),
            "total_pnl": round(total_pnl, 2),
            "avg_pnl_per_trade": round(total_pnl / len(closed_trades) if closed_trades else 0, 2),
            "max_drawdown": round(max_drawdown, 3),
            "sharpe_ratio": round(sharpe_ratio, 3),
            "profit_factor": round(profit_factor, 3) if math.isfinite(profit_factor) else float("inf"),
            "final_balance": round(self.balances[-1], 2),
            "trades_sample": closed_trades[:5],  # Premiers 5 trades
        }


def run_backtest_cli():
    """Entry point CLI."""
    instrument = sys.argv[1] if len(sys.argv) > 1 else "EURUSDm"
    days = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    
    try:
        broker = build_broker()
        backtest = SimpleBacktester(broker, instrument)
        stats = backtest.run_backtest(days)
        
        print("\n" + "="*60)
        print(f"  BACKTEST RESULTS — {instrument}")
        print("="*60)
        print(f"  Total trades: {stats.get('total_trades', 0)}")
        print(f"  Closed trades: {stats.get('closed_trades', 0)}")
        print(f"  Win rate: {stats.get('win_rate', 0):.1%}")
        print(f"  Total P&L: ${stats.get('total_pnl', 0):.2f}")
        print(f"  Avg P&L/trade: ${stats.get('avg_pnl_per_trade', 0):.2f}")
        print(f"  Max drawdown: {stats.get('max_drawdown', 0):.1%}")
        print(f"  Final balance: ${stats.get('final_balance', 1000):.2f}")
        print("="*60 + "\n")
        
        return stats
    except Exception as e:
        print(f"[BACKTEST] Erreur: {e}")
        import traceback
        traceback.print_exc()
        return {"error": str(e)}


if __name__ == "__main__":
    run_backtest_cli()
