"""
Risk Manager Dynamique : ajuste le risque par trade selon :
- Volatilité du jour (ATR)
- Série de pertes
- P&L du jour
"""

from datetime import datetime, timezone, timedelta
from typing import Dict, Optional


class DynamicRiskManager:
    """Gère le risque de manière adaptative."""

    def __init__(self):
        self.base_risk_pct = 0.02  # 2% par défaut
        self.daily_loss_limit = -5.0
        self.consecutive_losses = 0
        self.last_loss_time = None

    def calculate_adjusted_risk(
        self, 
        base_risk_pct: float,
        atr_value: float,
        atr_ma20: float,
        daily_pnl: float,
        consecutive_losses: int = 0,
        balance: float = 1000.0,
    ) -> float:
        """
        Calcule le risque ajusté en fonction de plusieurs facteurs.
        
        Returns: risque % à utiliser (par défaut 0.02, ajusté à la baisse si risqué)
        """
        adjusted = base_risk_pct
        
        # 1. Volatilité trop haute → réduit le risque
        if atr_ma20 > 0:
            volatility_ratio = atr_value / atr_ma20
            if volatility_ratio > 1.5:  # ATR 50% au-dessus de la moyenne
                reduction = 0.8 if volatility_ratio < 2.0 else 0.6
                adjusted = adjusted * reduction
        
        # 2. Série de pertes → réduit le risque progressivement
        if consecutive_losses > 0:
            # Après 1 perte : ×0.8, après 2 : ×0.6, après 3+ : ×0.4
            loss_multipliers = {
                1: 0.8,
                2: 0.6,
                3: 0.4,
                4: 0.3,
            }
            multiplier = loss_multipliers.get(consecutive_losses, 0.2)
            adjusted = adjusted * multiplier
        
        # 3. P&L du jour en perte → réduit progressivement
        if daily_pnl < 0:
            loss_pct_of_balance = abs(daily_pnl) / max(balance, 100)
            if loss_pct_of_balance > 0.05:  # 5% perte
                adjusted = adjusted * 0.7
            if loss_pct_of_balance > 0.10:  # 10% perte
                adjusted = adjusted * 0.5
        
        # Garder un minimum
        return max(adjusted, 0.005)  # Jamais moins de 0.5%

    def get_risk_multiplier(
        self,
        atr_value: float,
        atr_ma20: float,
        daily_pnl: float,
        consecutive_losses: int = 0,
    ) -> float:
        """Retourne le multiplicateur direct (0.2 = 20% du risque de base)."""
        base = 1.0
        
        # Volatilité
        if atr_ma20 > 0:
            vol_ratio = atr_value / atr_ma20
            if vol_ratio > 2.0:
                base *= 0.5
            elif vol_ratio > 1.5:
                base *= 0.7
        
        # Pertes consécutives
        if consecutive_losses >= 3:
            base *= 0.3
        elif consecutive_losses == 2:
            base *= 0.6
        elif consecutive_losses == 1:
            base *= 0.8
        
        # P&L du jour
        if daily_pnl < -0.10:  # 10% perte
            base *= 0.5
        elif daily_pnl < -0.05:  # 5% perte
            base *= 0.7
        
        return max(base, 0.2)  # Min 20% du risque de base

    def get_status_message(
        self,
        atr_value: float,
        atr_ma20: float,
        daily_pnl: float,
        consecutive_losses: int = 0,
        multiplier: float = 1.0,
    ) -> str:
        """Message explicatif du calcul de risque."""
        reasons = []
        
        if atr_ma20 > 0:
            vol_ratio = atr_value / atr_ma20
            if vol_ratio > 1.5:
                reasons.append(f"volatilité haute ({vol_ratio:.1f}x normal)")
        
        if consecutive_losses > 0:
            reasons.append(f"{consecutive_losses} pertes consécutives")
        
        if daily_pnl < -0.05:
            reasons.append(f"P&L jour: {daily_pnl*100:.1f}%")
        
        if multiplier < 1.0:
            msg = "Risque réduit à " + (f"{multiplier*100:.0f}%" if multiplier else "pause")
            if reasons:
                msg += f" ({', '.join(reasons)})"
            return msg
        
        return "Risque normal"


def calculate_atr_ma(atr_values: list, lookback: int = 20) -> float:
    """Calcule la MA des X derniers ATR."""
    if len(atr_values) < lookback:
        return sum(atr_values) / len(atr_values) if atr_values else 0.0
    return sum(atr_values[-lookback:]) / lookback
