"""
Module de calcul des stats de performance en temps réel.
Sharpe, Drawdown, Win rate, Profit Factor, etc.
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional


class PerformanceTracker:
    """Suivi des performances du bot en temps réel."""

    def __init__(self):
        self.trades = []
        self.balances_history = []
        self.daily_pnls = {}  # {YYYY-MM-DD: float}

    def add_trade(self, trade: Dict):
        """Enregistre un trade fermé."""
        if trade.get("pnl") is not None:
            self.trades.append(trade)
            
            # Enregistrer P&L du jour
            date_key = trade.get("timestamp", "").split("T")[0]
            if date_key:
                self.daily_pnls[date_key] = self.daily_pnls.get(date_key, 0) + trade["pnl"]

    def add_balance_snapshot(self, balance: float):
        """Enregistre un snapshot de balance."""
        self.balances_history.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "balance": balance,
        })

    def calculate_stats(self, reference_balance: float = 1000.0) -> Dict:
        """Calcule toutes les stats."""
        if not self.trades:
            return {
                "total_trades": 0,
                "win_rate": 0.0,
                "profit_factor": 0.0,
                "avg_win": 0.0,
                "avg_loss": 0.0,
                "expectancy": 0.0,
                "sharpe_ratio": 0.0,
                "max_drawdown": 0.0,
                "total_pnl": 0.0,
            }

        pnls = [t.get("pnl", 0) for t in self.trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]

        total_pnl = sum(pnls)
        win_rate = len(wins) / len(pnls) if pnls else 0.0
        
        # Profit factor = somme gains / somme pertes (abs)
        sum_wins = sum(wins) if wins else 0
        sum_losses = abs(sum(losses)) if losses else 0
        profit_factor = sum_wins / sum_losses if sum_losses > 0 else 0.0
        
        avg_win = sum_wins / len(wins) if wins else 0.0
        avg_loss = sum_losses / len(losses) if losses else 0.0
        
        # Expectancy = (win_rate × avg_win) - ((1-win_rate) × avg_loss)
        expectancy = (win_rate * avg_win) - ((1 - win_rate) * avg_loss) if pnls else 0.0
        
        # Sharpe (simplifié) = moyenne P&L / std P&L * sqrt(252)
        sharpe = self._calculate_sharpe(pnls)
        
        # Max drawdown
        max_dd = self._calculate_max_drawdown(reference_balance)

        return {
            "total_trades": len(pnls),
            "win_rate": round(win_rate, 3),
            "profit_factor": round(profit_factor, 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "expectancy": round(expectancy, 2),
            "sharpe_ratio": round(sharpe, 2),
            "max_drawdown": round(max_dd, 3),
            "total_pnl": round(total_pnl, 2),
            "consecutive_wins": self._get_consecutive_wins(),
            "consecutive_losses": self._get_consecutive_losses(),
        }

    def _calculate_sharpe(self, pnls: List[float]) -> float:
        """Calcule le ratio de Sharpe (simplifié)."""
        if len(pnls) < 2:
            return 0.0
        
        mean = sum(pnls) / len(pnls)
        variance = sum((p - mean) ** 2 for p in pnls) / len(pnls)
        std = variance ** 0.5
        
        if std == 0:
            return 0.0
        
        # Annualisé (supposant 252 jours de trading)
        return (mean / std) * (252 ** 0.5)

    def _calculate_max_drawdown(self, reference_balance: float) -> float:
        """Calcule le drawdown max."""
        if not self.trades:
            return 0.0
        
        peak = reference_balance
        max_dd = 0.0
        current_balance = reference_balance
        
        for trade in sorted(self.trades, key=lambda t: t.get("timestamp", "")):
            current_balance += trade.get("pnl", 0)
            if current_balance > peak:
                peak = current_balance
            drawdown = (peak - current_balance) / peak if peak > 0 else 0
            if drawdown > max_dd:
                max_dd = drawdown
        
        return max_dd

    def _get_consecutive_wins(self) -> int:
        """Retourne les gains consécutifs actuels."""
        count = 0
        for trade in reversed(self.trades):
            if trade.get("pnl", 0) > 0:
                count += 1
            else:
                break
        return count

    def _get_consecutive_losses(self) -> int:
        """Retourne les pertes consécutives actuelles."""
        count = 0
        for trade in reversed(self.trades):
            if trade.get("pnl", 0) < 0:
                count += 1
            else:
                break
        return count

    def get_daily_stats(self, date: str = None) -> Dict:
        """Retourne les stats pour un jour spécifique."""
        if date is None:
            date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        
        day_trades = [t for t in self.trades if t.get("timestamp", "").startswith(date)]
        day_pnl = sum(t.get("pnl", 0) for t in day_trades)
        
        return {
            "date": date,
            "trades": len(day_trades),
            "pnl": round(day_pnl, 2),
        }

    def get_monthly_stats(self) -> Dict:
        """Retourne les stats par mois."""
        monthly = {}
        for trade in self.trades:
            month_key = trade.get("timestamp", "")[:7]  # YYYY-MM
            if month_key not in monthly:
                monthly[month_key] = {"trades": 0, "pnl": 0.0}
            monthly[month_key]["trades"] += 1
            monthly[month_key]["pnl"] += trade.get("pnl", 0)
        
        return {k: {"trades": v["trades"], "pnl": round(v["pnl"], 2)} for k, v in sorted(monthly.items())}
