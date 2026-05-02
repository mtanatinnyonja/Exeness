"""
Circuit Breaker : pause automatique le trading si conditions dangereuses.

Règles :
- 3 pertes consécutives → pause 2h
- Daily loss > seuil → pause jour entier
- Slippage anormal → réduit risque
- Spread spike → wait
"""

from datetime import datetime, timezone, timedelta
import json
from typing import Dict, Optional

try:
    from runtime_db import RuntimeStore
except Exception:
    RuntimeStore = None


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
        self.store = None

        try:
            if RuntimeStore is None:
                raise RuntimeError("RuntimeStore import indisponible")
            self.store = RuntimeStore()
        except Exception as e:
            self._warn(f"RuntimeStore indisponible, fallback mémoire: {e}")

        self.daily_max_loss = self._load_daily_max_loss(default=-5.0)
        self.load_state()

    def _warn(self, message: str) -> None:
        print(f"[CircuitBreaker][WARN] {message}")

    def _load_daily_max_loss(self, default: float = -5.0) -> float:
        """Charge le seuil daily max loss depuis RuntimeStore si disponible."""
        if not self.store:
            return float(default)
        try:
            settings = self.store.get_settings()
            raw = settings.get("daily_max_loss", settings.get("daily_loss_limit", default))
            value = float(raw)
            if value > 0:
                self._warn(f"daily_max_loss positif ({value}), conversion en négatif")
                value = -abs(value)
            return value
        except Exception as e:
            self._warn(f"Impossible de charger daily_max_loss, fallback {default}: {e}")
            return float(default)

    def save_state(self) -> None:
        """Persiste l'état courant du circuit breaker en SQLite via RuntimeStore."""
        if not self.store:
            return
        payload = {
            "is_active": bool(self.is_active),
            "pause_reason": self.pause_reason,
            "pause_until": self.pause_until.isoformat() if self.pause_until else None,
            "consecutive_losses": int(self.consecutive_losses),
            "daily_max_loss": float(self.daily_max_loss),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            with self.store._connect() as conn:
                conn.execute(
                    "INSERT INTO settings(key, value, updated_at) VALUES (?, ?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                    (
                        self._STATE_KEY,
                        json.dumps(payload, ensure_ascii=False),
                        payload["updated_at"],
                    ),
                )
        except Exception as e:
            self._warn(f"save_state échoué, fallback mémoire: {e}")

    def load_state(self) -> None:
        """Charge l'état persisté et restaure une pause active si non expirée."""
        if not self.store:
            return
        try:
            with self.store._connect() as conn:
                row = conn.execute(
                    "SELECT value FROM settings WHERE key = ?",
                    (self._STATE_KEY,),
                ).fetchone()
            if not row or not row[0]:
                return

            state = json.loads(row[0])
            self.consecutive_losses = int(state.get("consecutive_losses", 0) or 0)

            raw_pause_until = state.get("pause_until")
            pause_until = None
            if raw_pause_until:
                pause_until = datetime.fromisoformat(str(raw_pause_until))
                if pause_until.tzinfo is None:
                    pause_until = pause_until.replace(tzinfo=timezone.utc)

            restored_daily = state.get("daily_max_loss")
            if restored_daily is not None:
                try:
                    self.daily_max_loss = float(restored_daily)
                except Exception:
                    pass

            if bool(state.get("is_active", False)) and pause_until and datetime.now(timezone.utc) < pause_until:
                self.is_active = True
                self.pause_reason = str(state.get("pause_reason", ""))
                self.pause_until = pause_until
            else:
                # Purger pause expirée/invalides tout en conservant le compteur pertes.
                self.is_active = False
                self.pause_reason = ""
                self.pause_until = None
                self.save_state()
        except Exception as e:
            self._warn(f"load_state échoué, fallback mémoire: {e}")

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
        self.save_state()
        if self.consecutive_losses >= self.consecutive_loss_threshold:
            self._activate_pause(
                f"{self.consecutive_losses} pertes consécutives",
                self.pause_duration_minutes
            )

    def record_win(self) -> None:
        """Reset compteur pertes après un gain."""
        self.consecutive_losses = 0
        self.save_state()

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
        self.save_state()

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
