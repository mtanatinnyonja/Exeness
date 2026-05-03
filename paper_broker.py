"""
Paper broker for Exeness.

Uses MT5 in read-only mode for market data (candles/spread/current price),
while simulating order execution and PnL locally.
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Dict, List, Optional, Tuple


class PaperBroker:
    """Drop-in paper trading broker with MT5 read-only market data."""

    def __init__(self):
        self.name = "paper"
        self.connected = True
        self.safe_to_trade = True
        self.last_error = ""
        self.status_message = "Paper trading actif"

        Path("data").mkdir(exist_ok=True)
        self._account_path = Path("data/paper_account.json")
        self._positions_path = Path("data/paper_positions.json")
        self._trades_path = Path("data/paper_trades.json")

        self._lock = Lock()
        self._positions: List[Dict] = []
        self._trades: List[Dict] = []
        self._account: Dict = {"balance": 10000.0, "equity": 10000.0, "currency": "USD"}
        self._next_ticket = int(datetime.now(timezone.utc).timestamp())

        self.mt5 = None
        self._init_mt5_readonly()
        self._load_state()

    # ------------------------------------------------------------------
    # MT5 read-only setup
    # ------------------------------------------------------------------

    def _init_mt5_readonly(self) -> None:
        try:
            import MetaTrader5 as mt5  # type: ignore

            self.mt5 = mt5
            if not self.mt5.initialize():
                err = self.mt5.last_error()
                raise RuntimeError(f"MT5 initialize failed: {err}")
            self.status_message = "Paper trading (prix reels MT5 read-only)"
        except Exception as e:
            self.mt5 = None
            self.connected = False
            self.last_error = f"MT5 read-only indisponible: {e}"
            self.status_message = self.last_error

    def _require_mt5(self) -> None:
        if self.mt5 is None:
            raise RuntimeError("MT5 non connecte: impossible de recuperer les prix reels (read-only)")

    def _timeframe(self, granularity: str):
        self._require_mt5()
        mapping = {
            "M1": self.mt5.TIMEFRAME_M1,
            "M5": self.mt5.TIMEFRAME_M5,
            "M15": self.mt5.TIMEFRAME_M15,
            "M30": self.mt5.TIMEFRAME_M30,
            "H1": self.mt5.TIMEFRAME_H1,
            "H4": self.mt5.TIMEFRAME_H4,
            "D1": self.mt5.TIMEFRAME_D1,
        }
        return mapping.get(granularity, self.mt5.TIMEFRAME_H1)

    def _resolve_symbol(self, instrument: str) -> str:
        self._require_mt5()
        base = str(instrument).replace("_", "")
        candidates = [instrument, base, base + "m", base + ".m", base + "pro", base + "i"]
        for candidate in candidates:
            info = self.mt5.symbol_info(candidate)
            if info is not None:
                self.mt5.symbol_select(info.name, True)
                return info.name

        symbols = self.mt5.symbols_get() or []
        for sym in symbols:
            name = getattr(sym, "name", "")
            if name.upper().startswith(base.upper()):
                self.mt5.symbol_select(name, True)
                return name
        raise RuntimeError(f"Symbole introuvable dans MT5 pour {instrument}")

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load_json(self, path: Path, default):
        if not path.exists():
            return default
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return payload
        except Exception:
            return default

    def _save_json(self, path: Path, payload) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    def _load_state(self) -> None:
        self._account = self._load_json(
            self._account_path,
            {"balance": 10000.0, "equity": 10000.0, "currency": "USD"},
        )
        self._positions = self._load_json(self._positions_path, [])
        self._trades = self._load_json(self._trades_path, [])

        max_ticket = 0
        for row in self._positions + self._trades:
            try:
                t = int(row.get("ticket") or row.get("broker_id") or 0)
                if t > max_ticket:
                    max_ticket = t
            except Exception:
                continue
        if max_ticket > 0:
            self._next_ticket = max_ticket + 1

    def _save_positions(self) -> None:
        self._save_json(self._positions_path, self._positions)

    def _save_account(self) -> None:
        self._save_json(self._account_path, self._account)

    def _append_trade(self, trade: Dict) -> None:
        self._trades.append(trade)
        self._save_json(self._trades_path, self._trades)

    # ------------------------------------------------------------------
    # Market data API
    # ------------------------------------------------------------------

    def get_candles(self, symbol: str, timeframe: str = "H1", count: int = 100) -> List[Dict]:
        self._require_mt5()
        mt5_symbol = self._resolve_symbol(symbol)
        rates = self.mt5.copy_rates_from_pos(mt5_symbol, self._timeframe(timeframe), 0, int(count))
        if rates is None or len(rates) == 0:
            raise RuntimeError(f"MT5 read-only: impossible de charger candles pour {mt5_symbol}")

        candles: List[Dict] = []
        for row in rates:
            candles.append(
                {
                    "time": datetime.fromtimestamp(int(row["time"]), timezone.utc).isoformat(),
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "tick_volume": int(row["tick_volume"]),
                }
            )
        return candles

    def _current_price(self, symbol: str) -> float:
        self._require_mt5()
        mt5_symbol = self._resolve_symbol(symbol)
        tick = self.mt5.symbol_info_tick(mt5_symbol)
        if tick is None:
            raise RuntimeError(f"Tick indisponible pour {mt5_symbol}")
        bid = float(getattr(tick, "bid", 0.0) or 0.0)
        ask = float(getattr(tick, "ask", 0.0) or 0.0)
        if bid <= 0 and ask <= 0:
            raise RuntimeError(f"Prix invalides pour {mt5_symbol}")
        if bid > 0 and ask > 0:
            return (bid + ask) / 2.0
        return ask if ask > 0 else bid

    def get_spread_pips(self, symbol: str) -> float:
        self._require_mt5()
        mt5_symbol = self._resolve_symbol(symbol)
        tick = self.mt5.symbol_info_tick(mt5_symbol)
        if tick is None:
            raise RuntimeError(f"Spread indisponible pour {mt5_symbol}")
        bid = float(getattr(tick, "bid", 0.0) or 0.0)
        ask = float(getattr(tick, "ask", 0.0) or 0.0)
        if bid <= 0 or ask <= 0:
            raise RuntimeError(f"Spread invalide pour {mt5_symbol}")
        pip = max(self._pip_size(mt5_symbol), 1e-10)
        return round((ask - bid) / pip, 1)

    # ------------------------------------------------------------------
    # Account / positions API
    # ------------------------------------------------------------------

    def _pip_size(self, instrument: str) -> float:
        name = str(instrument).upper()
        if self.mt5 is not None:
            try:
                info = self.mt5.symbol_info(self._resolve_symbol(instrument))
                point = float(getattr(info, "point", 0.0001) or 0.0001)
                digits = int(getattr(info, "digits", 5) or 5)
                if name.startswith(("XAU", "XAG")):
                    return max(point * 10, 0.10)
                if name.startswith(("BTC", "ETH")):
                    return max(point * 100, 1.0)
                return point * 10 if digits in {3, 5} else point
            except Exception:
                pass

        if name.startswith(("XAU", "XAG")):
            return 0.10
        if name.startswith(("BTC", "ETH")):
            return 1.0
        if "JPY" in name:
            return 0.01
        return 0.0001

    def _pip_value_per_lot(self, instrument: str) -> float:
        name = str(instrument).upper()
        if name.startswith(("BTC", "ETH")):
            return 1.0
        if name.startswith(("XAU", "XAG")):
            return 10.0
        return 10.0

    def calculate_volume(self, instrument: str, risk_usd: float, sl_pips: float) -> float:
        if sl_pips <= 0:
            return 0.01
        pv = self._pip_value_per_lot(instrument)
        vol = float(risk_usd) / max(0.01, float(sl_pips) * pv)
        vol = max(0.01, round(vol / 0.01) * 0.01)
        return round(vol, 2)

    def place_market_order(
        self,
        symbol: str,
        direction: str,
        volume: float,
        sl: Optional[float] = None,
        tp: Optional[float] = None,
        comment: str = "",
        stop_loss_pips: Optional[float] = None,
        take_profit_pips: Optional[float] = None,
    ) -> Optional[Dict]:
        """
        Simulated market order with real spread and random slippage.

        Supports both forms:
        - place_market_order(symbol, direction, volume, sl=<price>, tp=<price>)
        - place_market_order(..., stop_loss_pips=<pips>, take_profit_pips=<pips>)
        """
        side = str(direction).upper()
        pip = self._pip_size(symbol)
        current_price = self._current_price(symbol)
        spread = self.get_spread_pips(symbol)
        slippage_pips = random.uniform(0, 1.0)

        if side == "BUY":
            fill_price = current_price + (spread + slippage_pips) * pip
        else:
            fill_price = current_price - (spread + slippage_pips) * pip

        # Backward-compatible conversion from pips if needed.
        if sl is None and stop_loss_pips is not None:
            sl = fill_price - stop_loss_pips * pip if side == "BUY" else fill_price + stop_loss_pips * pip
        if tp is None and take_profit_pips is not None:
            tp = fill_price + take_profit_pips * pip if side == "BUY" else fill_price - take_profit_pips * pip

        if sl is None or tp is None:
            return None

        with self._lock:
            ticket = self._next_ticket
            self._next_ticket += 1
            opened_at = datetime.now(timezone.utc).isoformat()

            position = {
                "ticket": ticket,
                "broker_id": ticket,
                "position_ticket": ticket,
                "instrument": symbol,
                "direction": side,
                "volume": round(float(volume), 2),
                "units": round(float(volume), 2),
                "entry_price": float(fill_price),
                "avg_price": float(fill_price),
                "stop_loss": float(sl),
                "take_profit": float(tp),
                "sl": float(sl),
                "tp": float(tp),
                "spread_pips": float(spread),
                "slippage_pips": round(float(slippage_pips), 2),
                "status": "open",
                "timestamp": opened_at,
                "comment": comment,
            }
            self._positions.append(position)
            self._save_positions()

        return {
            "broker_id": ticket,
            "position_ticket": ticket,
            "instrument": symbol,
            "direction": side,
            "volume": round(float(volume), 2),
            "units": round(float(volume), 2),
            "entry_price": float(fill_price),
            "stop_loss": float(sl),
            "take_profit": float(tp),
            "status": "open",
        }

    def _position_unrealized_pnl(self, position: Dict) -> float:
        symbol = str(position.get("instrument", ""))
        side = str(position.get("direction", "BUY")).upper()
        entry = float(position.get("entry_price", 0.0) or 0.0)
        current = self._current_price(symbol)
        pip = max(self._pip_size(symbol), 1e-10)
        pip_value = self._pip_value_per_lot(symbol)
        move_pips = (current - entry) / pip if side == "BUY" else (entry - current) / pip
        return float(move_pips * pip_value * float(position.get("volume", 0.0) or 0.0))

    def get_open_positions(self) -> List[Dict]:
        with self._lock:
            rows: List[Dict] = []
            for p in self._positions:
                row = dict(p)
                current = self._current_price(row["instrument"])
                row["current_price"] = current
                row["price_current"] = current
                row["unrealized_pnl"] = round(self._position_unrealized_pnl(row), 2)
                rows.append(row)
            return rows

    def close_position(self, ticket) -> bool:
        """Close a paper position by ticket (or by instrument string for compatibility)."""
        with self._lock:
            to_close: Optional[Dict] = None

            if isinstance(ticket, str) and not ticket.isdigit():
                instrument = str(ticket).upper()
                for p in self._positions:
                    if str(p.get("instrument", "")).upper() == instrument:
                        to_close = p
                        break
            else:
                try:
                    tid = int(ticket)
                except Exception:
                    return False
                for p in self._positions:
                    if int(p.get("ticket", 0) or 0) == tid:
                        to_close = p
                        break

            if to_close is None:
                return False

            pnl = round(self._position_unrealized_pnl(to_close), 2)
            closed_at = datetime.now(timezone.utc).isoformat()

            self._positions = [p for p in self._positions if p is not to_close]
            self._save_positions()

            closed_trade = {
                "id": len(self._trades) + 1,
                "instrument": to_close.get("instrument"),
                "direction": to_close.get("direction"),
                "volume": to_close.get("volume"),
                "entry_price": to_close.get("entry_price"),
                "stop_loss": to_close.get("stop_loss"),
                "take_profit": to_close.get("take_profit"),
                "broker_id": to_close.get("broker_id"),
                "position_ticket": to_close.get("position_ticket"),
                "status": "closed",
                "timestamp": to_close.get("timestamp"),
                "pnl": pnl,
                "close_reason": "MANUAL_CLOSE",
                "closed_at": closed_at,
                "sl_pips": abs(float(to_close.get("entry_price", 0.0) or 0.0) - float(to_close.get("stop_loss", 0.0) or 0.0)) / max(self._pip_size(str(to_close.get("instrument", ""))), 1e-10),
                "tp_pips": abs(float(to_close.get("take_profit", 0.0) or 0.0) - float(to_close.get("entry_price", 0.0) or 0.0)) / max(self._pip_size(str(to_close.get("instrument", ""))), 1e-10),
                "risk_usd": None,
            }
            self._append_trade(closed_trade)

            # Account update
            balance = float(self._account.get("balance", 10000.0) or 10000.0)
            balance += pnl
            self._account["balance"] = round(balance, 2)
            self._account["equity"] = round(balance, 2)
            self._account.setdefault("currency", "USD")
            self._save_account()

            return True

    def modify_position(self, ticket: int, new_sl: float = None, new_tp: float = None, **kwargs) -> bool:
        if new_sl is None and "stop_loss" in kwargs:
            new_sl = kwargs.get("stop_loss")
        if new_tp is None and "take_profit" in kwargs:
            new_tp = kwargs.get("take_profit")

        with self._lock:
            target = None
            if isinstance(ticket, str) and not str(ticket).isdigit():
                inst = str(ticket).upper()
                for p in self._positions:
                    if str(p.get("instrument", "")).upper() == inst:
                        target = p
                        break
            else:
                try:
                    tid = int(ticket)
                except Exception:
                    return False
                for p in self._positions:
                    if int(p.get("ticket", 0) or 0) == tid:
                        target = p
                        break

            if target is None:
                return False
            if new_sl is not None:
                target["sl"] = float(new_sl)
                target["stop_loss"] = float(new_sl)
            if new_tp is not None:
                target["tp"] = float(new_tp)
                target["take_profit"] = float(new_tp)
            self._save_positions()
            return True

    def modify_sl(self, ticket_or_instrument, new_sl: float) -> bool:
        return self.modify_position(ticket_or_instrument, new_sl=new_sl, new_tp=None)

    def get_account_summary(self) -> Dict:
        with self._lock:
            balance = float(self._account.get("balance", 10000.0) or 10000.0)
            unrealized = 0.0
            for p in self._positions:
                unrealized += self._position_unrealized_pnl(p)
            equity = balance + unrealized

            self._account["equity"] = round(equity, 2)
            self._save_account()

            return {
                "balance": round(balance, 2),
                "equity": round(equity, 2),
                "unrealized_pnl": round(unrealized, 2),
                "nav": round(equity, 2),
                "open_trades": len(self._positions),
                "currency": str(self._account.get("currency", "USD") or "USD"),
                "is_cents": False,
                "display_currency": "$",
                "cents_ratio": 1,
                "connected": self.mt5 is not None,
                "provider": "paper",
            }

    # Optional compatibility helpers used by other components.
    def list_visible_symbols(self) -> List[str]:
        self._require_mt5()
        symbols = self.mt5.symbols_get() or []
        visible = [getattr(sym, "name", "") for sym in symbols if getattr(sym, "visible", False)]
        return [s for s in visible if s]

    def get_active_symbols(self, fallback: Optional[List[str]] = None) -> List[str]:
        source = fallback or self.list_visible_symbols()
        uniq: List[str] = []
        for s in source:
            if s and s not in uniq:
                uniq.append(s)
        return uniq[:10]

    def get_market_status(self, symbols: Optional[List[str]] = None, max_tick_age_sec: int = 3600) -> Dict:
        self._require_mt5()
        symbol = (symbols or [None])[0]
        if symbol is None:
            active = self.get_active_symbols()
            symbol = active[0] if active else None
        if not symbol:
            return {"open": False, "symbol": None, "tick_age_sec": None, "reason": "Aucun symbole"}

        mt5_symbol = self._resolve_symbol(symbol)
        tick = self.mt5.symbol_info_tick(mt5_symbol)
        if tick is None:
            return {"open": False, "symbol": mt5_symbol, "tick_age_sec": None, "reason": "Tick indisponible"}

        tick_time = datetime.fromtimestamp(int(getattr(tick, "time", 0) or 0), timezone.utc)
        age_sec = max(0, int((datetime.now(timezone.utc) - tick_time).total_seconds()))
        return {
            "open": age_sec <= int(max_tick_age_sec),
            "symbol": mt5_symbol,
            "tick_age_sec": age_sec,
            "reason": "Tick MT5 read-only" if age_sec <= int(max_tick_age_sec) else "Tick stale",
        }

    def get_signal_outcome_label(self, instrument: str, sample_time: str, direction: str, spread: float = 0.0, horizon_minutes: int = 15) -> Optional[int]:
        try:
            candles = self.get_candles(instrument, "M1", max(20, int(horizon_minutes) + 2))
            if len(candles) < 5:
                return None
            entry = float(candles[0].get("open", 0.0) or 0.0)
            exit_price = float(candles[-1].get("close", 0.0) or 0.0)
            pip = max(self._pip_size(instrument), 1e-6)
            move = (exit_price - entry) / pip
            signed = move if str(direction).upper() == "BUY" else -move
            threshold = max(1.0, float(spread or 0.0) * 0.15)
            return 1 if signed > threshold else 0
        except Exception:
            return None
