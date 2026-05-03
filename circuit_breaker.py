"""
Circuit Breaker : pause automatique le trading si conditions dangereuses.

Règles :
- 3 pertes consécutives → pause 2h
- Daily loss > seuil → pause jour entier
- Slippage anormal → réduit risque
- Spread spike → wait
"""

from datetime import datetime, timezone, timedelta
from typing import Dict

try:
    from runtime_db import RuntimeStore
    _STORE_AVAILABLE = True
except ImportError:
    _STORE_AVAILABLE = False


class CircuitBreaker:
    """Coupe-circuit pour trading autonome."""

    _STATE_KEY = "circuit_breaker_state"

    def __init__(self):
        self.is_active = False  # True = trading pause
        self.pause_reason = ""
        self.pause_until = None
        self.consecutive_losses = 0
        self.daily_max_loss = -5.0  # USD
        self.consecutive_loss_threshold = 3
        self.pause_duration_minutes = 120  # 2h après 3 pertes
        self._load_state()

    def _warn(self, message: str) -> None:
        print(f"[CircuitBreaker][WARN] {message}")

    def _load_state(self):
        if not _STORE_AVAILABLE:
            return
        try:
            store = RuntimeStore()
            self.consecutive_losses = int(store.get("cb_consecutive_losses") or 0)
            self.daily_max_loss = float(store.get("daily_max_loss") or -5.0)
            pause_str = store.get("cb_pause_until") or ""
            if pause_str:
                self.pause_until = datetime.fromisoformat(pause_str)
                if self.pause_until > datetime.now(timezone.utc):
                    self.is_active = True
                    self.pause_reason = store.get("cb_pause_reason") or "restaurée"
        except Exception:
            pass  # fallback mémoire silencieux

    def _save_state(self):
        if not _STORE_AVAILABLE:
            return
        try:
            store = RuntimeStore()
            store.set("cb_consecutive_losses", str(self.consecutive_losses))
            store.set("cb_pause_until", self.pause_until.isoformat() if self.pause_until else "")
            store.set("cb_pause_reason", self.pause_reason)
        except Exception:
            pass

    def save_state(self) -> None:
        self._save_state()

    def load_state(self) -> None:
        self._load_state()

    def reset_daily(self):
        """Reset état pour un nouveau jour."""
        self.consecutive_losses = 0
        self.is_active = False
        self.pause_reason = ""
        self.pause_until = None
        self.save_state()

    def check_pause_expired(self) -> bool:
        """Vérifie si la pause a expiré."""
        if not self.pause_until:
            return False
        if datetime.now(timezone.utc) >= self.pause_until:
            self.is_active = False
            self.pause_reason = ""
            self.pause_until = None
            self.save_state()
            return True
        return False

    def record_loss(self) -> None:
        """Enregistre une perte (fermeture P&L négatif)."""
        self.consecutive_losses += 1
        self._save_state()
        if self.consecutive_losses >= self.consecutive_loss_threshold:
            self._activate_pause(
                f"{self.consecutive_losses} pertes consécutives",
                self.pause_duration_minutes
            )

    def record_win(self) -> None:
        """Reset compteur pertes après un gain."""
        self.consecutive_losses = 0
        self._save_state()

    def check_daily_loss_exceeded(self, daily_pnl: float) -> bool:
        """Vérifie si la perte journalière dépasse le seuil."""
        if daily_pnl <= self.daily_max_loss:
            self._activate_pause(
                f"Perte journalière dépassée: {daily_pnl:.2f}$",
                1440  # 24h
            )
            return True
        return False

    def check_spread_spike(self, current_spread: float, normal_spread: float, spike_ratio: float = 3.0) -> bool:
        """Vérifie si le spread a un spike anormal."""
        if normal_spread <= 0:
            return False
        if current_spread > normal_spread * spike_ratio:
            # Pause courte, juste pour attendre que le spread se normalise
            self._activate_pause(
                f"Spread spike: {current_spread:.1f}p (normal {normal_spread:.1f}p)",
                15  # 15 min
            )
            return True
        return False

    def check_slippage_anomaly(self, expected_fill: float, actual_fill: float, 
                                instrument: str, pips_threshold: float = 5.0) -> bool:
        """Vérifie si le slippage est anormalement élevé."""
        pip_size = self._get_pip_size(instrument)
        slippage_pips = abs(actual_fill - expected_fill) / pip_size
        if slippage_pips > pips_threshold:
            self._activate_pause(
                f"Slippage anormal {slippage_pips:.1f}p sur {instrument}",
                30  # 30 min
            )
            return True
        return False

    def _activate_pause(self, reason: str, duration_minutes: int):
        """Active la pause."""
        self.is_active = True
        self.pause_reason = reason
        self.pause_until = datetime.now(timezone.utc) + timedelta(minutes=duration_minutes)
        self._save_state()

    def get_status(self) -> Dict:
        """Retourne le statut du circuit breaker."""
        self.check_pause_expired()
        
        if self.is_active and self.pause_until:
            remaining = (self.pause_until - datetime.now(timezone.utc)).total_seconds() / 60
            return {
                "is_paused": True,
                "reason": self.pause_reason,
                "pause_until": self.pause_until.isoformat(),
                "remaining_minutes": max(0, remaining),
            }
        
        return {
            "is_paused": False,
            "consecutive_losses": self.consecutive_losses,
        }

    def can_trade(self) -> bool:
        """Vérifie si le trading est autorisé."""
        self.check_pause_expired()
        return not self.is_active

    def _get_pip_size(self, instrument: str) -> float:
        """Retourne la taille pip pour un instrument."""
        name = str(instrument).upper()
        if name.startswith(("XAU", "XAG")):
            return 0.10
        if name.startswith(("BTC", "ETH")):
            return 1.0
        if "JPY" in name:
            return 0.01
        return 0.0001
