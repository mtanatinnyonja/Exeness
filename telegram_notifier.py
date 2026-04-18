"""
Notifications Telegram pour événements importants du bot.
Envoie des alertes pour: trades ouverts/fermés, P&L journalier,
erreurs critiques, pauses marché, et résumés.
"""

import threading
from datetime import datetime, timezone
from typing import Optional

try:
    import requests as _requests
except ImportError:
    _requests = None

from runtime_db import RuntimeStore


class TelegramNotifier:
    """Envoie des notifications Telegram via Bot API (non bloquant)."""

    def __init__(self):
        self.store = RuntimeStore()
        self._refresh_config()
        self._last_daily_summary = ""

    def _refresh_config(self):
        settings = self.store.get_settings()
        raw_enabled = settings.get("telegram_enabled", True)
        self.enabled = bool(raw_enabled) if isinstance(raw_enabled, bool) else str(raw_enabled).lower() in {"true", "1", "yes"}
        self.bot_token = str(settings.get("telegram_bot_token", "")).strip()
        self.chat_id = str(settings.get("telegram_chat_id", "")).strip()

    def _is_ready(self) -> bool:
        if not _requests:
            return False
        self._refresh_config()
        return bool(self.enabled and self.bot_token and self.chat_id)

    def _send_async(self, text: str):
        """Envoie le message dans un thread séparé pour ne pas bloquer le bot."""
        if not self._is_ready():
            return
        # Tronquer les messages très longs (Telegram max ~4096)
        if len(text) > 4000:
            text = text[:3997] + "..."

        def _do_send():
            try:
                url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
                _requests.post(url, json={
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                }, timeout=10)
            except Exception:
                pass  # Silencieux — ne jamais bloquer le bot pour Telegram

        t = threading.Thread(target=_do_send, daemon=True)
        t.start()

    # ── Événements publics ──────────────────────────────────────────

    def notify_trade_opened(self, instrument: str, direction: str, volume: float,
                            entry_price: float, sl_pips: int, tp_pips: int,
                            confidence: float, risk_usd: float, reasoning: str = ""):
        emoji = "🟢" if direction == "BUY" else "🔴"
        text = (
            f"{emoji} <b>TRADE OUVERT</b>\n"
            f"<b>{instrument}</b> {direction}\n"
            f"Vol: {volume} | Entry: {entry_price:.5f}\n"
            f"SL: {sl_pips}p | TP: {tp_pips}p | RR: {tp_pips/max(1,sl_pips):.1f}\n"
            f"Confiance: {confidence:.0%} | Risque: ${risk_usd:.2f}\n"
        )
        if reasoning:
            text += f"<i>{reasoning[:200]}</i>"
        self._send_async(text)

    def notify_trade_closed(self, instrument: str, direction: str, pnl: float,
                            close_reason: str = ""):
        emoji = "💰" if pnl >= 0 else "💸"
        text = (
            f"{emoji} <b>TRADE FERMÉ</b>\n"
            f"<b>{instrument}</b> {direction}\n"
            f"P&L: <b>${pnl:+.2f}</b> | Raison: {close_reason or '?'}"
        )
        self._send_async(text)

    def notify_daily_summary(self, balance: float, daily_pnl: float,
                             total_trades: int, win_rate: float,
                             open_positions: int):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self._last_daily_summary == today:
            return  # Déjà envoyé aujourd'hui
        self._last_daily_summary = today

        emoji = "📈" if daily_pnl >= 0 else "📉"
        text = (
            f"📊 <b>RÉSUMÉ JOURNALIER</b> {today}\n"
            f"Balance: <b>${balance:.2f}</b>\n"
            f"{emoji} P&L jour: <b>${daily_pnl:+.2f}</b>\n"
            f"Trades: {total_trades} | Win rate: {win_rate:.0%}\n"
            f"Positions ouvertes: {open_positions}"
        )
        self._send_async(text)

    def notify_error(self, context: str, error: str):
        text = (
            f"🚨 <b>ERREUR</b>\n"
            f"<b>{context}</b>\n"
            f"<code>{str(error)[:300]}</code>"
        )
        self._send_async(text)

    def notify_news_pause(self, instrument: str, reason: str):
        text = f"📰 <b>PAUSE NEWS</b>\n{instrument}: {reason}"
        self._send_async(text)

    def notify_daily_loss_limit(self, pnl: float, limit: float):
        text = (
            f"🛑 <b>LIMITE PERTE ATTEINTE</b>\n"
            f"P&L: ${pnl:.2f} ≤ limite ${limit:.2f}\n"
            f"Toutes les positions fermées."
        )
        self._send_async(text)

    def notify_bot_started(self, broker: str, provider: str, symbols: list):
        text = (
            f"🚀 <b>BOT DÉMARRÉ</b>\n"
            f"Broker: {broker} | IA: {provider}\n"
            f"Symboles: {', '.join(symbols[:10]) if symbols else 'scan dynamique'}"
        )
        self._send_async(text)

    def notify_trailing_stop(self, instrument: str, action: str, old_sl: float, new_sl: float):
        text = (
            f"🔄 <b>TRAILING STOP</b>\n"
            f"{instrument}: {action}\n"
            f"SL: {old_sl:.5f} → {new_sl:.5f}"
        )
        self._send_async(text)

    def send_custom(self, message: str):
        """Envoi libre pour messages personnalisés."""
        self._send_async(message)

    def test_connection(self) -> dict:
        """Teste la connexion Telegram et retourne le résultat."""
        if not _requests:
            return {"ok": False, "error": "module requests non installé"}
        self._refresh_config()
        if not self.bot_token or not self.chat_id:
            return {"ok": False, "error": "token ou chat_id manquant"}
        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            resp = _requests.post(url, json={
                "chat_id": self.chat_id,
                "text": "✅ Bot trading connecté à Telegram!",
                "parse_mode": "HTML",
            }, timeout=10)
            data = resp.json()
            if data.get("ok"):
                return {"ok": True, "message_id": data.get("result", {}).get("message_id")}
            return {"ok": False, "error": data.get("description", "erreur inconnue")}
        except Exception as e:
            return {"ok": False, "error": str(e)}
