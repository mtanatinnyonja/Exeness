"""
Paper broker for Exeness.

Simulates order execution while using MT5 read-only market data when available.
Open positions are persisted in data/paper_positions.json.
Closed trades are appended to data/paper_trades.json.
"""

from __future__ import annotations

import json
import math
import os
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from typing import Dict, List, Optional, Tuple

from settings import (
    INITIAL_CAPITAL,
    INSTRUMENTS,
    MT5_MAX_VISIBLE_SYMBOLS,
    PREFERRED_SYMBOLS,
)


class PaperBroker:
    def __init__(self, start_balance: float = 10000.0):
        self.name = "paper"
        self.connected = True
        self.safe_to_trade = True
        self.last_error = ""
        self.status_message = "Paper trading actif"

        self._start_balance = float(os.getenv("PAPER_START_BALANCE", start_balance) or start_balance)
        self._positions_path = Path("data/paper_positions.json")
        self._trades_path = Path("data/paper_trades.json")
        self._lock = Lock()

        self._positions: List[Dict] = []
        self._trades: List[Dict] = []
        self._next_ticket = int(datetime.now(timezone.utc).timestamp())

        self.mt5 = None
        self._init_mt5_readonly()
        self._load_state()

    # ---------- setup ----------

    def _init_mt5_readonly(self) -> None:
        try:
            import MetaTrader5 as mt5  # type: ignore

            self.mt5 = mt5
            if not self.mt5.initialize():
                self.last_error = f"MT5 init read-only failed: {self.mt5.last_error()}"
                self.mt5 = None
                self.status_message = "Paper trading (prix synthétiques)"
            else:
                self.status_message = "Paper trading (prix MT5 read-only)"
        except Exception as e:
            self.last_error = f"MetaTrader5 indisponible: {e}"
            self.mt5 = None
            self.status_message = "Paper trading (prix synthétiques)"

    def _ensure_data_dir(self) -> None:
        self._positions_path.parent.mkdir(parents=True, exist_ok=True)

    def _load_state(self) -> None:
        self._ensure_data_dir()
        try:
            if self._positions_path.exists():
                raw = json.loads(self._positions_path.read_text(encoding="utf-8"))
                self._positions = raw if isinstance(raw, list) else []
            if self._trades_path.exists():
                raw = json.loads(self._trades_path.read_text(encoding="utf-8"))
                self._trades = raw if isinstance(raw, list) else []
        except Exception:
            self._positions = []
            self._trades = []

        max_ticket = 0
        for row in self._positions + self._trades:
            try:
                max_ticket = max(max_ticket, int(row.get("ticket") or row.get("broker_id") or 0))
            except Exception:
                continue
        if max_ticket > 0:
            self._next_ticket = max_ticket + 1

    def _persist_positions(self) -> None:
        self._ensure_data_dir()
        self._positions_path.write_text(
            json.dumps(self._positions, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

    def _persist_trades(self) -> None:
        self._ensure_data_dir()
        self._trades_path.write_text(
            json.dumps(self._trades, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

    # ---------- market data ----------

    def _timeframe(self, granularity: str):
        if not self.mt5:
            return None
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
        if not self.mt5:
            return instrument
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
        return instrument

    def get_candles(self, instrument: str, granularity: str = "H1", count: int = 100) -> List[Dict]:
        symbol = self._resolve_symbol(instrument)
        if self.mt5:
            try:
                rates = self.mt5.copy_rates_from_pos(symbol, self._timeframe(granularity), 0, count)
                if rates is not None and len(rates) > 0:
                    candles = []
                    for row in rates:
                        candles.append(
                            {
                                "time": datetime.fromtimestamp(int(row["time"]), timezone.utc).isoformat(),
                                "open": float(row["open"]),
                                "high": float(row["high"]),
                                "low": float(row["low"]),
                                "close": float(row["close"]),
                                "tick_volume": int(row.get("tick_volume", 0) if hasattr(row, "get") else row["tick_volume"]),
                                "volume": int(row.get("tick_volume", 0) if hasattr(row, "get") else row["tick_volume"]),
                            }
                        )
                    return candles
            except Exception:
                pass

        # Synthetic fallback if MT5 quotes are unavailable.
        base = 1.08 if "EUR" in symbol.upper() else 1.27 if "GBP" in symbol.upper() else 1900.0
        now = datetime.now(timezone.utc)
        candles: List[Dict] = []
        for i in range(max(2, int(count))):
            wave = math.sin(i / 4.0) * (0.0015 if base < 10 else 2.0)
            drift = (i - count / 2.0) * (0.00003 if base < 10 else 0.04)
            close = base + wave + drift
            open_price = close - (0.0004 if base < 10 else 0.5)
            high = max(open_price, close) + (0.0007 if base < 10 else 0.8)
            low = min(open_price, close) - (0.0007 if base < 10 else 0.8)
            candles.append(
                {
                    "time": (now - timedelta(minutes=max(0, count - i))).isoformat(),
                    "open": round(open_price, 5 if base < 10 else 2),
                    "high": round(high, 5 if base < 10 else 2),
                    "low": round(low, 5 if base < 10 else 2),
                    "close": round(close, 5 if base < 10 else 2),
                    "tick_volume": 100 + i,
                    "volume": 100 + i,
                }
            )
        return candles

    def get_current_price(self, instrument: str) -> Tuple[float, float]:
        symbol = self._resolve_symbol(instrument)
        if self.mt5:
            try:
                tick = self.mt5.symbol_info_tick(symbol)
                if tick is not None:
                    bid = float(getattr(tick, "bid", 0.0) or 0.0)
                    ask = float(getattr(tick, "ask", 0.0) or 0.0)
                    if bid > 0 and ask > 0:
                        return bid, ask
            except Exception:
                pass

        candles = self.get_candles(symbol, "M1", 2)
        mid = float(candles[-1]["close"])
        spread = self._pip_size(symbol) * 1.5
        return mid - spread / 2, mid + spread / 2

    def get_spread_pips(self, instrument: str) -> float:
        symbol = self._resolve_symbol(instrument)
        bid, ask = self.get_current_price(symbol)
        pip = max(self._pip_size(symbol), 1e-10)
        return round((ask - bid) / pip, 1)

    # ---------- sizing ----------

    def _pip_size(self, instrument: str) -> float:
        name = str(instrument).upper()
        if self.mt5:
            try:
                info = self.mt5.symbol_info(self._resolve_symbol(instrument))
                if info is not None:
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
        return 10.0

    def _volume_min(self, instrument: str) -> float:
        if self.mt5:
            try:
                info = self.mt5.symbol_info(self._resolve_symbol(instrument))
                if info is not None:
                    return float(getattr(info, "volume_min", 0.01) or 0.01)
            except Exception:
                pass
        return 0.01

    def _volume_step(self, instrument: str) -> float:
        if self.mt5:
            try:
                info = self.mt5.symbol_info(self._resolve_symbol(instrument))
                if info is not None:
                    return float(getattr(info, "volume_step", 0.01) or 0.01)
            except Exception:
                pass
        return 0.01

    def calculate_volume(self, instrument: str, risk_usd: float, sl_pips: float) -> float:
        if sl_pips <= 0:
            return self._volume_min(instrument)
        pv = self._pip_value_per_lot(instrument)
        vol = float(risk_usd) / max(0.01, float(sl_pips) * pv)
        step = self._volume_step(instrument)
        vol = max(self._volume_min(instrument), round(vol / step) * step)
        return round(vol, 2)

    # ---------- positions ----------

    def _unrealized_pnl(self, position: Dict) -> float:
        bid, ask = self.get_current_price(position["instrument"])
        direction = str(position.get("direction", "BUY")).upper()
        current = bid if direction == "BUY" else ask
        entry = float(position.get("entry_price", 0.0) or 0.0)
        pip = max(self._pip_size(position["instrument"]), 1e-10)
        pips = (current - entry) / pip if direction == "BUY" else (entry - current) / pip
        value_per_lot = self._pip_value_per_lot(position["instrument"])
        return round(pips * value_per_lot * float(position.get("volume", 0.0) or 0.0), 2)

    def place_market_order(
        self,
        instrument: str,
        direction: str,
        volume: float,
        stop_loss_pips: float,
        take_profit_pips: float,
        comment: str = "",
    ) -> Optional[Dict]:
        symbol = self._resolve_symbol(instrument)
        direction = str(direction).upper()
        bid, ask = self.get_current_price(symbol)
        pip = max(self._pip_size(symbol), 1e-10)

        # Simulated execution with real spread + random slippage 0-1 pip.
        base_entry = ask if direction == "BUY" else bid
        slippage_pips = random.uniform(0.0, 1.0)
        slip = slippage_pips * pip
        entry_price = base_entry + slip if direction == "BUY" else base_entry - slip

        sl = entry_price - stop_loss_pips * pip if direction == "BUY" else entry_price + stop_loss_pips * pip
        tp = entry_price + take_profit_pips * pip if direction == "BUY" else entry_price - take_profit_pips * pip

        with self._lock:
            ticket = self._next_ticket
            self._next_ticket += 1
            now_iso = datetime.now(timezone.utc).isoformat()
            pos = {
                "ticket": ticket,
                "broker_id": ticket,
                "position_ticket": ticket,
                "instrument": symbol,
                "direction": direction,
                "volume": round(float(volume), 2),
                "units": round(float(volume), 2),
                "entry_price": float(entry_price),
                "avg_price": float(entry_price),
                "price_current": float(entry_price),
                "sl": float(sl),
                "tp": float(tp),
                "stop_loss": float(sl),
                "take_profit": float(tp),
                "sl_pips": float(stop_loss_pips),
                "tp_pips": float(take_profit_pips),
                "status": "open",
                "timestamp": now_iso,
                "comment": comment,
                "slippage_pips": round(slippage_pips, 2),
                "spread_pips": self.get_spread_pips(symbol),
            }
            self._positions.append(pos)
            self._persist_positions()

        return {
            "broker_id": ticket,
            "position_ticket": ticket,
            "instrument": symbol,
            "direction": direction,
            "volume": round(float(volume), 2),
            "units": round(float(volume), 2),
            "entry_price": float(entry_price),
            "stop_loss": float(sl),
            "take_profit": float(tp),
            "status": "open",
            "slippage_pips": round(slippage_pips, 2),
        }

    def get_open_positions(self) -> List[Dict]:
        with self._lock:
            rows = []
            for p in self._positions:
                row = dict(p)
                pnl = self._unrealized_pnl(row)
                bid, ask = self.get_current_price(row["instrument"])
                direction = str(row.get("direction", "BUY")).upper()
                current = bid if direction == "BUY" else ask
                row["price_current"] = current
                row["current_price"] = current
                row["unrealized_pnl"] = pnl
                rows.append(row)
            return rows

    def close_position(self, instrument: str) -> Optional[float]:
        symbol = self._resolve_symbol(instrument)
        with self._lock:
            open_rows = [p for p in self._positions if str(p.get("instrument", "")).upper() == str(symbol).upper()]
            if not open_rows:
                return 0.0

            total = 0.0
            for pos in open_rows:
                pnl = self._unrealized_pnl(pos)
                total += pnl
                closed = dict(pos)
                closed["status"] = "closed"
                closed["pnl"] = round(pnl, 2)
                closed["close_reason"] = "MANUAL_CLOSE"
                closed["closed_at"] = datetime.now(timezone.utc).isoformat()
                closed["id"] = len(self._trades) + 1
                self._trades.append(closed)

            self._positions = [p for p in self._positions if p not in open_rows]
            self._persist_positions()
            self._persist_trades()

        return round(total, 2)

    def modify_position(self, ticket: int, new_sl: float = None, new_tp: float = None, **kwargs) -> bool:
        # Backward-compatible kwargs used by some callers.
        if new_sl is None and "stop_loss" in kwargs:
            new_sl = kwargs.get("stop_loss")
        if new_tp is None and "take_profit" in kwargs:
            new_tp = kwargs.get("take_profit")

        with self._lock:
            # Accept either ticket or instrument string in first arg for compatibility.
            target = None
            if isinstance(ticket, str) and not ticket.isdigit():
                inst = self._resolve_symbol(ticket)
                for p in self._positions:
                    if str(p.get("instrument", "")).upper() == str(inst).upper():
                        target = p
                        break
            else:
                t = int(ticket)
                for p in self._positions:
                    if int(p.get("ticket", 0) or 0) == t:
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
            self._persist_positions()
            return True

    def modify_sl(self, ticket_or_instrument, new_sl: float) -> bool:
        return self.modify_position(ticket_or_instrument, new_sl=new_sl, new_tp=None)

    # ---------- account ----------

    def get_account_summary(self) -> Dict:
        with self._lock:
            realized = sum(float(t.get("pnl", 0.0) or 0.0) for t in self._trades)
            unrealized = sum(self._unrealized_pnl(p) for p in self._positions)
            balance = self._start_balance + realized
            equity = balance + unrealized
            return {
                "balance": round(balance, 2),
                "unrealized_pnl": round(unrealized, 2),
                "nav": round(equity, 2),
                "open_trades": len(self._positions),
                "currency": "USD",
                "connected": True,
                "provider": "paper",
            }

    # ---------- symbols / status ----------

    def list_visible_symbols(self) -> List[str]:
        if self.mt5:
            try:
                symbols = self.mt5.symbols_get() or []
                visible = [getattr(sym, "name", "") for sym in symbols if getattr(sym, "visible", False)]
                return [s for s in visible if s]
            except Exception:
                pass
        return list(PREFERRED_SYMBOLS) if PREFERRED_SYMBOLS else list(INSTRUMENTS)

    def get_active_symbols(self, fallback: Optional[List[str]] = None) -> List[str]:
        pool = fallback or self.list_visible_symbols() or list(PREFERRED_SYMBOLS) or list(INSTRUMENTS)
        uniq: List[str] = []
        for s in pool:
            if s and s not in uniq:
                uniq.append(s)
        return uniq[: int(MT5_MAX_VISIBLE_SYMBOLS)]

    def get_market_status(self, symbols: Optional[List[str]] = None, max_tick_age_sec: int = 3600) -> Dict:
        now = datetime.now(timezone.utc)
        scheduled = now.weekday() < 5
        symbol = (symbols or self.get_active_symbols() or [None])[0]
        return {
            "open": scheduled,
            "symbol": symbol,
            "tick_age_sec": 0,
            "reason": "Paper trading actif" if scheduled else "Fenetre de marche fermee",
        }

    def get_signal_outcome_label(
        self,
        instrument: str,
        sample_time: str,
        direction: str,
        spread: float = 0.0,
        horizon_minutes: int = 15,
    ) -> Optional[int]:
        try:
            start = datetime.fromisoformat(str(sample_time).replace("Z", "+00:00"))
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
            candles = self.get_candles(instrument, "M1", max(20, horizon_minutes + 2))
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
