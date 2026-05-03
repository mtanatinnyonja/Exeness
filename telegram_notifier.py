"""
Notifications Telegram pour événements importants du bot.
Envoie des alertes pour: trades ouverts/fermés, P&L journalier,
erreurs critiques, pauses marché, et résumés.
"""

import asyncio
import hashlib
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

try:
    import requests as _requests
except ImportError:
    _requests = None

from runtime_db import RuntimeStore


class TelegramNotifier:
    """Envoie des notifications Telegram via Bot API (non bloquant)."""

    _loop: Optional[asyncio.AbstractEventLoop] = None
    _queue: Optional[asyncio.Queue] = None
    _worker_task: Optional[asyncio.Task] = None
    _poller_task: Optional[asyncio.Task] = None
    _details_cache: Dict[str, Dict[str, Any]] = {}
    _details_order: list[str] = []
    _updates_offset: int = 0
    _last_send_ts: float = 0.0
    _min_interval_sec: float = 1.0 / 30.0
    _dispatcher_lock = threading.Lock()

    def __init__(self):
        self.store = RuntimeStore()
        self._refresh_config()
        self._last_daily_summary = ""

    @staticmethod
    def _md_escape(value: Any) -> str:
        text = str(value)
        for ch in "_*[]()~`>#+-=|{}.!":
            text = text.replace(ch, f"\\{ch}")
        return text

    def _make_trade_details_token(self, payload: Dict[str, Any]) -> str:
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
        token = f"d{digest}"
        TelegramNotifier._details_cache[token] = payload
        TelegramNotifier._details_order.append(token)
        # Limite mémoire cache détails
        while len(TelegramNotifier._details_order) > 500:
            old = TelegramNotifier._details_order.pop(0)
            TelegramNotifier._details_cache.pop(old, None)
        return token

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

    @classmethod
    def _has_dispatcher(cls) -> bool:
        return bool(cls._loop and cls._queue and cls._worker_task and not cls._worker_task.done())

    def start_async_dispatcher(self, loop: asyncio.AbstractEventLoop):
        """Initialise la queue async + worker + poller callbacks Telegram."""
        if not self._is_ready():
            return

        with TelegramNotifier._dispatcher_lock:
            if TelegramNotifier._has_dispatcher():
                return
            TelegramNotifier._loop = loop
            TelegramNotifier._queue = asyncio.Queue()
            TelegramNotifier._worker_task = loop.create_task(self._queue_worker(), name="telegram-queue-worker")
            TelegramNotifier._poller_task = loop.create_task(self._poll_callbacks_loop(), name="telegram-callback-poller")

    async def stop_async_dispatcher(self):
        """Arrête proprement les tâches async Telegram."""
        tasks = [TelegramNotifier._worker_task, TelegramNotifier._poller_task]
        for task in tasks:
            if task and not task.done():
                task.cancel()
        for task in tasks:
            if task:
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    pass
        TelegramNotifier._worker_task = None
        TelegramNotifier._poller_task = None
        TelegramNotifier._queue = None

    async def _queue_worker(self):
        while True:
            queue = TelegramNotifier._queue
            if queue is None:
                await asyncio.sleep(0.2)
                continue
            payload = await queue.get()
            try:
                await self._send_http_payload(payload)
            finally:
                queue.task_done()

    async def _send_http_payload(self, payload: Dict[str, Any]):
        # Rate limiting Telegram Bot API: 30 msg/s max global
        now = asyncio.get_running_loop().time()
        elapsed = now - TelegramNotifier._last_send_ts
        wait_s = TelegramNotifier._min_interval_sec - elapsed
        if wait_s > 0:
            await asyncio.sleep(wait_s)

        self._refresh_config()
        if not self.bot_token:
            return
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"

        async def _post_once(req_payload: Dict[str, Any]):
            def _post():
                return _requests.post(url, json=req_payload, timeout=10)
            return await asyncio.to_thread(_post)

        try:
            # Retry court pour erreurs réseau/5xx/429
            for attempt in range(3):
                resp = await _post_once(payload)
                status_code = int(getattr(resp, "status_code", 0) or 0)
                data = {}
                try:
                    data = resp.json() if resp is not None else {}
                except Exception:
                    data = {}

                if 200 <= status_code < 300 and bool(data.get("ok", True)):
                    break

                # Cas fréquent Telegram: erreur de parsing MarkdownV2
                description = str(data.get("description", "") or "")
                if (
                    status_code == 400
                    and payload.get("parse_mode") == "MarkdownV2"
                    and "parse" in description.lower()
                ):
                    payload_plain = dict(payload)
                    payload_plain.pop("parse_mode", None)
                    resp_plain = await _post_once(payload_plain)
                    status_plain = int(getattr(resp_plain, "status_code", 0) or 0)
                    if 200 <= status_plain < 300:
                        print("[TelegramNotifier] markdown parse error: fallback plain text succeeded")
                        break

                if status_code in (429, 500, 502, 503, 504) and attempt < 2:
                    await asyncio.sleep(0.8 * (attempt + 1))
                    continue

                print(f"[TelegramNotifier] sendMessage failed status={status_code} description={description[:220]}")
                break
        except Exception as exc:
            print(f"[TelegramNotifier] sendMessage exception: {exc}")
        finally:
            TelegramNotifier._last_send_ts = asyncio.get_running_loop().time()

    async def _poll_callbacks_loop(self):
        while True:
            try:
                if not self._is_ready():
                    await asyncio.sleep(2.0)
                    continue

                url = f"https://api.telegram.org/bot{self.bot_token}/getUpdates"
                payload = {
                    "timeout": 20,
                    "allowed_updates": ["callback_query"],
                }
                if TelegramNotifier._updates_offset > 0:
                    payload["offset"] = TelegramNotifier._updates_offset

                def _get():
                    return _requests.post(url, json=payload, timeout=25)

                resp = await asyncio.to_thread(_get)
                data = resp.json() if resp is not None else {}
                updates = data.get("result", []) if isinstance(data, dict) else []
                for upd in updates:
                    update_id = int(upd.get("update_id", 0) or 0)
                    if update_id:
                        TelegramNotifier._updates_offset = update_id + 1
                    callback = upd.get("callback_query") or {}
                    if callback:
                        await self._handle_callback(callback)
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(1.5)

    async def _handle_callback(self, callback: Dict[str, Any]):
        callback_id = str(callback.get("id", ""))
        data = str(callback.get("data", ""))
        message = callback.get("message", {}) or {}
        chat_id = (message.get("chat") or {}).get("id") or self.chat_id

        if data.startswith("details:"):
            token = data.split(":", 1)[1].strip()
            details = TelegramNotifier._details_cache.get(token)
            if details:
                body = self._format_details_message(details)
                self._enqueue_payload({
                    "chat_id": chat_id,
                    "text": body,
                    "parse_mode": "MarkdownV2",
                    "disable_web_page_preview": True,
                })
                await self._answer_callback(callback_id, "Détails envoyés")
            else:
                await self._answer_callback(callback_id, "Détails indisponibles")

    async def _answer_callback(self, callback_id: str, text: str):
        if not callback_id:
            return
        url = f"https://api.telegram.org/bot{self.bot_token}/answerCallbackQuery"
        payload = {
            "callback_query_id": callback_id,
            "text": text[:180],
            "show_alert": False,
        }

        def _post():
            return _requests.post(url, json=payload, timeout=10)

        try:
            resp = await asyncio.to_thread(_post)
            if resp is not None and getattr(resp, "status_code", 0) >= 400:
                print(f"[TelegramNotifier] answerCallbackQuery failed status={resp.status_code}")
        except Exception as exc:
            print(f"[TelegramNotifier] answerCallbackQuery exception: {exc}")

    def _format_details_message(self, details: Dict[str, Any]) -> str:
        lines = ["*🔍 Détails signal*", ""]
        for key in sorted(details.keys()):
            value = details.get(key)
            if isinstance(value, float):
                val = f"{value:.6f}".rstrip("0").rstrip(".")
            else:
                val = str(value)
            lines.append(f"• *{self._md_escape(key)}*: {self._md_escape(val)}")
        txt = "\n".join(lines)
        if len(txt) > 4000:
            txt = txt[:3997] + "..."
        return txt

    def _enqueue_payload(self, payload: Dict[str, Any]):
        if not self._is_ready():
            return
        queue = TelegramNotifier._queue
        loop = TelegramNotifier._loop
        if queue is None or loop is None:
            # Fallback best-effort si dispatcher async non initialisé.
            try:
                url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
                resp = _requests.post(url, json=payload, timeout=10)
                if resp is not None and getattr(resp, "status_code", 0) >= 400:
                    print(f"[TelegramNotifier] fallback sendMessage failed status={resp.status_code}")
            except Exception as exc:
                print(f"[TelegramNotifier] fallback sendMessage exception: {exc}")
            return

        def _put_nowait():
            try:
                queue.put_nowait(payload)
            except Exception:
                pass

        try:
            if loop.is_running():
                loop.call_soon_threadsafe(_put_nowait)
            else:
                _put_nowait()
        except Exception:
            pass

    def _send_async(self, text: str):
        """Compatibilité descendante: envoie texte simple en MarkdownV2."""
        if not self._is_ready():
            return
        escaped = self._md_escape(text)
        if len(escaped) > 4000:
            escaped = escaped[:3997] + "..."
        self._enqueue_payload({
            "chat_id": self.chat_id,
            "text": escaped,
            "parse_mode": "MarkdownV2",
            "disable_web_page_preview": True,
        })

    # ── Événements publics ──────────────────────────────────────────

    def notify_trade_opened(self, instrument: str, direction: str, volume: float,
                            entry_price: float, sl_pips: int, tp_pips: int,
                            confidence: float, risk_usd: float, reasoning: str = ""):
        self.send_trade_alert(
            trade_data={
                "instrument": instrument,
                "direction": direction,
                "volume": volume,
                "entry": entry_price,
                "sl": sl_pips,
                "tp": tp_pips,
                "confidence": confidence,
                "risk_usd": risk_usd,
                "reasoning": reasoning,
            },
            signal_details={},
        )

    def send_trade_alert(self, trade_data: Dict[str, Any], signal_details: Dict[str, Any]):
        """
        Envoie une alerte trade enrichie en Markdown + bouton inline Détails.
        """
        if not self._is_ready():
            return

        instrument = str(trade_data.get("instrument", "?") or "?")
        direction = str(trade_data.get("direction", "?") or "?").upper()
        emoji = "📈" if direction == "BUY" else "📉"
        volume = float(trade_data.get("volume", 0.0) or 0.0)
        entry = float(trade_data.get("entry", trade_data.get("entry_price", 0.0)) or 0.0)

        sl_raw = trade_data.get("sl", trade_data.get("stop_loss", trade_data.get("sl_pips", 0)))
        tp_raw = trade_data.get("tp", trade_data.get("take_profit", trade_data.get("tp_pips", 0)))
        score = int(trade_data.get("signal_score", trade_data.get("score", 0)) or 0)

        quality = float(signal_details.get("quality_score", 0.0) or 0.0)
        regime = str(signal_details.get("market_regime", "unknown") or "unknown")
        rsi = float(signal_details.get("rsi", 0.0) or 0.0)
        pattern = str(signal_details.get("candle_pattern", "none") or "none")
        rr_key = "rr_buy" if direction == "BUY" else "rr_sell"
        rr_ratio = float(signal_details.get(rr_key, 0.0) or 0.0)

        # Fallback RR si non fourni dans details.
        if rr_ratio <= 0:
            try:
                sl_num = float(sl_raw)
                tp_num = float(tp_raw)
                if "pips" in str(type(sl_raw)).lower() or "pips" in str(type(tp_raw)).lower():
                    rr_ratio = tp_num / max(1.0, sl_num)
                elif sl_num > 0 and tp_num > 0:
                    rr_ratio = tp_num / max(1.0, sl_num)
            except Exception:
                rr_ratio = 0.0

        line1 = (
            f"{emoji} *{self._md_escape(instrument)} {self._md_escape(direction)}* \\| "
            f"Score: *{score}/5* \\| RSI: *{rsi:.1f}* \\| {self._md_escape(pattern)} \\| "
            f"R:R *{rr_ratio:.2f}* \\| Regime: *{self._md_escape(regime)}*"
        )
        line2 = (
            f"Vol: {self._md_escape(f'{volume:.2f}')} \\| "
            f"Entry: {self._md_escape(f'{entry:.5f}')}"
        )
        line3 = f"SL: {self._md_escape(str(sl_raw))} \\| TP: {self._md_escape(str(tp_raw))}"
        line4 = f"Qualité: *{quality:.2f}*"

        text = "\n".join([line1, line2, line3, line4])
        details_token = self._make_trade_details_token(signal_details or {})
        reply_markup = {
            "inline_keyboard": [
                [
                    {
                        "text": "🔍 Détails",
                        "callback_data": f"details:{details_token}",
                    }
                ]
            ]
        }
        self._enqueue_payload({
            "chat_id": self.chat_id,
            "text": text[:4000],
            "parse_mode": "MarkdownV2",
            "disable_web_page_preview": True,
            "reply_markup": reply_markup,
        })

    def notify_trade_closed(self, instrument: str, direction: str, pnl: float,
                            close_reason: str = "", reason: str = ""):
        close_reason = close_reason or reason
        emoji = "💰" if pnl >= 0 else "💸"
        text = (
            f"{emoji} TRADE FERME\n"
            f"{instrument} {direction}\n"
            f"PnL: ${pnl:+.2f} | Raison: {close_reason or '?'}"
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
            f"📊 RESUME JOURNALIER {today}\n"
            f"Balance: ${balance:.2f}\n"
            f"{emoji} PnL jour: ${daily_pnl:+.2f}\n"
            f"Trades: {total_trades} | Win rate: {win_rate:.0%}\n"
            f"Positions ouvertes: {open_positions}"
        )
        self._send_async(text)

    def send_daily_summary(self):
        """Construit et envoie le résumé journalier basé sur data/trades_history.json."""
        if not self._is_ready():
            return

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self._last_daily_summary == today:
            return

        trades_file = Path("data/trades_history.json")
        trades = []
        if trades_file.exists():
            try:
                trades = json.loads(trades_file.read_text(encoding="utf-8"))
            except Exception:
                trades = []

        day_trades = []
        for t in trades:
            if not isinstance(t, dict):
                continue
            if str(t.get("status", "")).lower() != "closed":
                continue
            ts = str(t.get("closed_at") or t.get("timestamp") or "")
            if ts.startswith(today):
                day_trades.append(t)

        total = len(day_trades)
        winners = [t for t in day_trades if float(t.get("pnl", 0.0) or 0.0) > 0]
        losers = [t for t in day_trades if float(t.get("pnl", 0.0) or 0.0) <= 0]
        pnl_total = sum(float(t.get("pnl", 0.0) or 0.0) for t in day_trades)
        win_rate = (len(winners) / total * 100.0) if total else 0.0

        best_trade = max(day_trades, key=lambda x: float(x.get("pnl", 0.0) or 0.0), default=None)
        worst_trade = min(day_trades, key=lambda x: float(x.get("pnl", 0.0) or 0.0), default=None)

        best_line = "-"
        if best_trade:
            best_line = (
                f"{best_trade.get('instrument', '?')} "
                f"{best_trade.get('direction', '?')} "
                f"${float(best_trade.get('pnl', 0.0) or 0.0):+.2f}"
            )
        worst_line = "-"
        if worst_trade:
            worst_line = (
                f"{worst_trade.get('instrument', '?')} "
                f"{worst_trade.get('direction', '?')} "
                f"${float(worst_trade.get('pnl', 0.0) or 0.0):+.2f}"
            )

        text = (
            f"*📊 Résumé quotidien* {self._md_escape(today)}\n"
            f"Trades: *{total}* \\(✅ {len(winners)} / ❌ {len(losers)}\\)\n"
            f"P&L total: *{self._md_escape(f'${pnl_total:+.2f}')}*\n"
            f"Win rate: *{win_rate:.1f}%*\n"
            f"Meilleur trade: {self._md_escape(best_line)}\n"
            f"Pire trade: {self._md_escape(worst_line)}"
        )

        self._enqueue_payload({
            "chat_id": self.chat_id,
            "text": text[:4000],
            "parse_mode": "MarkdownV2",
            "disable_web_page_preview": True,
        })
        self._last_daily_summary = today

    def notify_error(self, context: str, error: str):
        text = (
            f"🚨 ERREUR\n"
            f"{context}\n"
            f"{str(error)[:300]}"
        )
        self._send_async(text)

    def notify_news_pause(self, instrument: str, reason: str):
        text = f"📰 PAUSE NEWS\n{instrument}: {reason}"
        self._send_async(text)

    def notify_daily_loss_limit(self, pnl: float, limit: float):
        text = (
            f"🛑 LIMITE PERTE ATTEINTE\n"
            f"P&L: ${pnl:.2f} ≤ limite ${limit:.2f}\n"
            f"Toutes les positions fermées."
        )
        self._send_async(text)

    def notify_bot_started(self, broker: str, provider: str, symbols: list):
        text = (
            f"🚀 BOT DEMARRE\n"
            f"Broker: {broker} | IA: {provider}\n"
            f"Symboles: {', '.join(symbols[:10]) if symbols else 'scan dynamique'}"
        )
        self._send_async(text)

    def notify_trailing_stop(self, instrument: str, action: str, old_sl: float, new_sl: float):
        text = (
            f"🔄 TRAILING STOP\n"
            f"{instrument}: {action}\n"
            f"SL: {old_sl:.5f} -> {new_sl:.5f}"
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
                "text": "✅ Bot trading connecté à Telegram",
            }, timeout=10)
            data = resp.json()
            if data.get("ok"):
                return {
                    "ok": True,
                    "message": "Message test envoyé avec succès",
                    "message_id": data.get("result", {}).get("message_id"),
                }
            return {"ok": False, "error": data.get("description", "erreur inconnue")}
        except Exception as e:
            return {"ok": False, "error": str(e)}
