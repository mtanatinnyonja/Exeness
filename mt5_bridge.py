"""
Pont local vers MT5.
Aucun broker cloud: seulement MT5 déjà ouvert ou paper trading local.
"""

import math
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple

from settings import (
    BROKER, INITIAL_CAPITAL, MT5_TERMINAL_PATH, MT5_LOGIN, MT5_PASSWORD,
    MT5_SERVER, REQUIRE_DEMO_ACCOUNT, ALLOW_TRADE_EXECUTION,
    MT5_MAGIC_NUMBER, MT5_DEVIATION, PAPER_TRADING,
    MT5_MAX_VISIBLE_SYMBOLS, PREFERRED_SYMBOLS,
)
from runtime_db import RuntimeStore
from paper_broker import PaperBroker as ExternalPaperBroker


class PaperBroker:
    def __init__(self, reason: str = "Mode paper local"):
        self.name = "paper"
        self.connected = False
        self.safe_to_trade = False
        self.last_error = reason
        self.status_message = reason
        self.mt5 = None

    def get_account_summary(self) -> Dict:
        return {
            "balance": INITIAL_CAPITAL,
            "unrealized_pnl": 0.0,
            "nav": INITIAL_CAPITAL,
            "open_trades": 0,
            "currency": "USD",
            "connected": False,
            "provider": "paper",
        }

    def get_open_positions(self) -> List[Dict]:
        return []

    def get_candles(self, instrument: str, granularity: str = "H1", count: int = 100) -> List[Dict]:
        base = 1.08 if "EUR" in instrument else 1.27 if "GBP" in instrument else 1900.0
        candles = []
        now = datetime.now(timezone.utc)
        for i in range(count):
            wave = math.sin(i / 4) * (0.0015 if base < 10 else 2.0)
            drift = (i - count / 2) * (0.00003 if base < 10 else 0.04)
            close = base + wave + drift
            open_price = close - (0.0004 if base < 10 else 0.5)
            high = max(open_price, close) + (0.0007 if base < 10 else 0.8)
            low = min(open_price, close) - (0.0007 if base < 10 else 0.8)
            candles.append({
                "time": now.isoformat(),
                "open": round(open_price, 5 if base < 10 else 2),
                "high": round(high, 5 if base < 10 else 2),
                "low": round(low, 5 if base < 10 else 2),
                "close": round(close, 5 if base < 10 else 2),
                "volume": 100 + i,
            })
        return candles

    def get_current_price(self, instrument: str) -> Tuple[float, float]:
        candles = self.get_candles(instrument, count=2)
        mid = candles[-1]["close"]
        spread = 0.0002 if "JPY" not in instrument else 0.02
        return mid - spread / 2, mid + spread / 2

    def _pip_size(self, instrument: str) -> float:
        name = str(instrument).upper()
        if name.startswith(("XAU", "XAG")):
            return 0.10
        if name.startswith(("BTC", "ETH")):
            return 1.0
        if "JPY" in name:
            return 0.01
        return 0.0001

    def _pip_value_per_lot(self, instrument: str) -> float:
        name = str(instrument).upper()
        if name.startswith(("XAU", "XAG")):
            return 10.0
        if name.startswith(("BTC", "ETH")):
            return 1.0
        return 10.0

    def _volume_min(self, instrument: str) -> float:
        return 0.01

    def _volume_step(self, instrument: str) -> float:
        return 0.01

    def get_spread_pips(self, instrument: str) -> float:
        bid, ask = self.get_current_price(instrument)
        return round((ask - bid) / self._pip_size(instrument), 1)

    def calculate_volume(self, instrument: str, risk_usd: float, sl_pips: float) -> float:
        if sl_pips <= 0:
            return self._volume_min(instrument)
        pv = self._pip_value_per_lot(instrument)
        vol = risk_usd / max(0.01, sl_pips * pv)
        step = self._volume_step(instrument)
        vol = max(self._volume_min(instrument), round(vol / step) * step)
        return round(vol, 2)

    def place_market_order(self, instrument: str, direction: str, volume: float, stop_loss_pips: float, take_profit_pips: float, comment: str = "") -> Optional[Dict]:
        bid, ask = self.get_current_price(instrument)
        entry = ask if direction == "BUY" else bid
        pip = self._pip_size(instrument)
        return {
            "broker_id": f"paper-{int(datetime.now(timezone.utc).timestamp())}",
            "instrument": instrument,
            "direction": direction,
            "volume": round(volume, 2),
            "entry_price": entry,
            "stop_loss": entry - stop_loss_pips * pip if direction == "BUY" else entry + stop_loss_pips * pip,
            "take_profit": entry + take_profit_pips * pip if direction == "BUY" else entry - take_profit_pips * pip,
            "status": "paper",
            "comment": comment,
        }

    def close_position(self, instrument: str) -> Optional[float]:
        return 0.0

    def modify_sl(self, ticket_or_instrument, new_sl: float) -> bool:
        return False

    def list_visible_symbols(self) -> List[str]:
        return []

    def get_active_symbols(self, fallback: Optional[List[str]] = None) -> List[str]:
        return []

    def modify_position(self, ticket: int, new_sl: float = None, new_tp: float = None) -> bool:
        return False

    def get_market_status(self, symbols: Optional[List[str]] = None, max_tick_age_sec: int = 3600) -> Dict:
        now = datetime.now(timezone.utc)
        scheduled = now.weekday() < 5
        return {
            "open": scheduled,
            "symbol": (symbols or [None])[0],
            "tick_age_sec": 0,
            "reason": "Mode paper local" if scheduled else "Fenêtre de marché fermée en mode paper",
        }

    def get_signal_outcome_label(self, instrument: str, sample_time: str, direction: str, spread: float = 0.0, horizon_minutes: int = 15) -> Optional[int]:
        try:
            start = datetime.fromisoformat(str(sample_time).replace('Z', '+00:00'))
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
            end = start + timedelta(minutes=horizon_minutes)
            candles = self.get_candles(instrument, 'M1', max(20, horizon_minutes + 2))
            if len(candles) < 5:
                return None
            entry = float(candles[0].get('open', 0) or 0)
            exit_price = float(candles[-1].get('close', 0) or 0)
            pip = max(self._pip_size(instrument), 1e-6)
            move = (exit_price - entry) / pip
            signed = move if str(direction).upper() == 'BUY' else -move
            threshold = max(1.0, float(spread or 0) * 0.15)
            return 1 if signed > threshold else 0
        except Exception:
            return None


class MT5Broker:
    def __init__(self):
        self.name = "mt5"
        self.connected = False
        self.safe_to_trade = False
        self.last_error = ""
        self.status_message = ""
        self.mt5 = None
        self._init_mt5()

    def _init_mt5(self):
        try:
            import MetaTrader5 as mt5
            self.mt5 = mt5
        except Exception as e:
            self.last_error = f"Package MetaTrader5 indisponible: {e}"
            self.status_message = self.last_error
            return

        kwargs = {}
        if MT5_TERMINAL_PATH:
            kwargs["path"] = MT5_TERMINAL_PATH

        if not self.mt5.initialize(**kwargs):
            self.last_error = f"MT5 non initialisé: {self.mt5.last_error()}"
            self.status_message = self.last_error
            return

        if MT5_LOGIN and MT5_PASSWORD and MT5_SERVER:
            self.mt5.login(int(MT5_LOGIN), password=MT5_PASSWORD, server=MT5_SERVER)

        account = self.mt5.account_info()
        if account is None:
            self.last_error = "MT5 détecté, mais aucun compte connecté."
            self.status_message = self.last_error
            return

        self.connected = True
        is_demo = self._is_demo_account(account)
        runtime = RuntimeStore().get_settings()
        self.safe_to_trade = bool(is_demo and runtime.get("allow_trade_execution", ALLOW_TRADE_EXECUTION))
        server = getattr(account, "server", "")
        company = getattr(account, "company", "")
        login = getattr(account, "login", "")

        if REQUIRE_DEMO_ACCOUNT and not is_demo:
            self.status_message = f"Compte MT5 connecté ({server}) détecté en lecture seule, pas en démo."
        elif self.safe_to_trade:
            self.status_message = f"MT5 démo détecté et prêt au trading: {login} @ {server}"
        else:
            self.status_message = f"MT5 détecté: {login} @ {server} ({company}) - mode analyse/paper"

    def _is_demo_account(self, account) -> bool:
        server = f"{getattr(account, 'server', '')} {getattr(account, 'company', '')}".lower()
        return "demo" in server or "trial" in server or getattr(account, "trade_mode", None) == 0

    def _ensure_ready(self):
        if not self.connected or self.mt5 is None:
            raise RuntimeError(self.last_error or "MT5 non connecté")

    def _describe_trade_retcode(self, code) -> str:
        descriptions = {
            10004: "requote",
            10017: "trade disabled (broker/account)",
            10018: "market closed",
            10019: "not enough money",
            10024: "too many requests",
            10027: "client disables auto trading",
            10031: "no connection",
        }
        try:
            return descriptions.get(int(code), "unknown trade retcode")
        except Exception:
            return "unknown trade retcode"

    def _resolve_symbol(self, instrument: str) -> str:
        self._ensure_ready()
        base = instrument.replace("_", "")
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

    def _timeframe(self, granularity: str):
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

    def _pip_size(self, symbol: str) -> float:
        info = self.mt5.symbol_info(symbol) if self.mt5 else None
        point = float(getattr(info, "point", 0.0001) or 0.0001)
        digits = int(getattr(info, "digits", 5) or 5)
        name = str(symbol).upper()
        if name.startswith(("XAU", "XAG")):
            return max(point * 10, 0.10)
        if name.startswith(("BTC", "ETH")):
            return max(point * 100, 1.0)
        return point * 10 if digits in {3, 5} else point

    def _pip_factor(self, symbol: str) -> float:
        return 1.0 / max(self._pip_size(symbol), 1e-10)

    def _pip_value_per_lot(self, symbol: str) -> float:
        info = self.mt5.symbol_info(symbol) if self.mt5 else None
        tick_size = float(getattr(info, "trade_tick_size", 0.0001) or 0.0001)
        tick_value = float(getattr(info, "trade_tick_value", 0.01) or 0.01)
        pip = self._pip_size(symbol)
        return (pip / tick_size) * tick_value

    def _volume_min(self, symbol: str) -> float:
        info = self.mt5.symbol_info(symbol) if self.mt5 else None
        return float(getattr(info, "volume_min", 0.01) or 0.01)

    def _volume_step(self, symbol: str) -> float:
        info = self.mt5.symbol_info(symbol) if self.mt5 else None
        return float(getattr(info, "volume_step", 0.01) or 0.01)

    def list_visible_symbols(self) -> List[str]:
        self._ensure_ready()
        symbols = self.mt5.symbols_get() or []
        visible = [getattr(sym, "name", "") for sym in symbols if getattr(sym, "visible", False)]
        return [name for name in visible if name]

    def get_active_symbols(self, fallback: Optional[List[str]] = None) -> List[str]:
        self._ensure_ready()
        settings = RuntimeStore().get_settings()
        positions = [getattr(pos, "symbol", "") for pos in (self.mt5.positions_get() or [])]
        visible = self.list_visible_symbols()
        max_symbols = int(settings.get("max_symbols_per_cycle", MT5_MAX_VISIBLE_SYMBOLS))

        preferred_raw = fallback or settings.get("preferred_symbols", PREFERRED_SYMBOLS) or []
        preferred = []
        for raw in preferred_raw:
            if not raw:
                continue
            raw_str = str(raw).strip()
            candidates = [raw_str, raw_str.replace("_", ""), raw_str.upper(), raw_str.lower()]
            matched = None
            for candidate in candidates:
                for name in visible + positions:
                    if str(name).upper() == candidate.upper():
                        matched = name
                        break
                if matched:
                    break
            preferred.append(matched or raw_str)

        source = preferred + positions + visible
        ordered = []
        for name in source:
            if name and name not in ordered:
                ordered.append(name)

        return ordered[:max_symbols]

    def get_market_status(self, symbols: Optional[List[str]] = None, max_tick_age_sec: int = 3600) -> Dict:
        self._ensure_ready()
        now = datetime.now(timezone.utc)
        candidates = list(symbols or self.get_active_symbols())
        freshest = None
        live_symbols = []

        for instrument in candidates:
            try:
                symbol = self._resolve_symbol(instrument)
                tick = self.mt5.symbol_info_tick(symbol)
                if tick is None:
                    continue
                tick_time = datetime.fromtimestamp(int(getattr(tick, "time", 0) or 0), timezone.utc)
                age_sec = max(0, int((now - tick_time).total_seconds()))
                bid = float(getattr(tick, "bid", 0.0) or 0.0)
                ask = float(getattr(tick, "ask", 0.0) or 0.0)
                is_live = age_sec <= max_tick_age_sec and (bid > 0 or ask > 0)
                entry = {
                    "open": is_live,
                    "symbol": symbol,
                    "tick_age_sec": age_sec,
                    "tick_time": tick_time.isoformat(),
                    "bid": bid,
                    "ask": ask,
                }
                if is_live:
                    live_symbols.append(symbol)
                if freshest is None or age_sec < freshest.get("tick_age_sec", 10**9):
                    freshest = entry
            except Exception:
                continue

        if freshest:
            symbols_label = ", ".join(live_symbols) if live_symbols else freshest["symbol"]
            freshest["reason"] = (
                f"Cotations MT5 live sur {symbols_label} · dernier tick {freshest['tick_age_sec']}s"
                if freshest["open"]
                else f"Pas de tick récent sur {freshest['symbol']} · {freshest['tick_age_sec']}s"
            )
            freshest["live_symbols"] = live_symbols
            return freshest

        return {
            "open": False,
            "symbol": candidates[0] if candidates else None,
            "tick_age_sec": None,
            "reason": "Aucune cotation MT5 disponible",
            "live_symbols": [],
        }

    def get_signal_outcome_label(self, instrument: str, sample_time: str, direction: str, spread: float = 0.0, horizon_minutes: int = 15) -> Optional[int]:
        self._ensure_ready()
        symbol = self._resolve_symbol(instrument)
        start = datetime.fromisoformat(str(sample_time).replace('Z', '+00:00'))
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        end = start + timedelta(minutes=horizon_minutes)
        rates = self.mt5.copy_rates_range(symbol, self.mt5.TIMEFRAME_M1, start, end)
        if rates is None or len(rates) < 5:
            return None
        entry = float(rates[0]['open'])
        exit_price = float(rates[-1]['close'])
        move = (exit_price - entry) * self._pip_factor(symbol)
        signed = move if str(direction).upper() == 'BUY' else -move
        threshold = max(1.0, float(spread or 0) * 0.15)
        return 1 if signed > threshold else 0

    def get_account_summary(self) -> Dict:
        self._ensure_ready()
        account = self.mt5.account_info()
        runtime = RuntimeStore().get_settings()
        is_demo = self._is_demo_account(account)
        self.safe_to_trade = bool(is_demo and runtime.get("allow_trade_execution", ALLOW_TRADE_EXECUTION))
        server = getattr(account, "server", "")
        company = getattr(account, "company", "")
        login = getattr(account, "login", "")
        if self.safe_to_trade:
            self.status_message = f"MT5 démo actif pour trading automatique: {login} @ {server} ({company})"
        else:
            self.status_message = f"MT5 détecté: {login} @ {server} ({company}) - mode analyse/paper"
        return {
            "balance": float(getattr(account, "balance", INITIAL_CAPITAL)),
            "unrealized_pnl": float(getattr(account, "profit", 0.0)),
            "nav": float(getattr(account, "equity", INITIAL_CAPITAL)),
            "open_trades": len(self.mt5.positions_get() or []),
            "currency": getattr(account, "currency", "USD"),
            "connected": True,
            "provider": "mt5",
            "server": getattr(account, "server", ""),
            "login": getattr(account, "login", ""),
            "demo_detected": self._is_demo_account(account),
        }

    def get_open_positions(self) -> List[Dict]:
        self._ensure_ready()
        positions = []
        for pos in self.mt5.positions_get() or []:
            direction = "BUY" if pos.type == self.mt5.POSITION_TYPE_BUY else "SELL"
            positions.append({
                "ticket": getattr(pos, "ticket", None),
                "instrument": pos.symbol,
                "direction": direction,
                "units": getattr(pos, "volume", 0.0),
                "unrealized_pnl": float(getattr(pos, "profit", 0.0)),
                "avg_price": float(getattr(pos, "price_open", 0.0)),
                "sl": float(getattr(pos, "sl", 0.0) or 0.0),
                "tp": float(getattr(pos, "tp", 0.0) or 0.0),
                "price_current": float(getattr(pos, "price_current", 0.0) or 0.0),
            })
        return positions

    def get_candles(self, instrument: str, granularity: str = "H1", count: int = 100) -> List[Dict]:
        self._ensure_ready()
        symbol = self._resolve_symbol(instrument)
        rates = self.mt5.copy_rates_from_pos(symbol, self._timeframe(granularity), 0, count)
        if rates is None:
            raise RuntimeError(f"copy_rates_from_pos a échoué pour {symbol}: {self.mt5.last_error()}")

        candles = []
        for row in rates:
            candles.append({
                "time": datetime.utcfromtimestamp(int(row["time"])).isoformat(),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": int(row["tick_volume"]),
            })
        return candles

    def get_current_price(self, instrument: str) -> Tuple[float, float]:
        self._ensure_ready()
        symbol = self._resolve_symbol(instrument)
        tick = self.mt5.symbol_info_tick(symbol)
        if tick is None:
            raise RuntimeError(f"Tick indisponible pour {symbol}")
        return float(tick.bid), float(tick.ask)

    def get_spread_pips(self, instrument: str) -> float:
        symbol = self._resolve_symbol(instrument)
        bid, ask = self.get_current_price(instrument)
        return round((ask - bid) * self._pip_factor(symbol), 1)

    def calculate_volume(self, instrument: str, risk_usd: float, sl_pips: float) -> float:
        symbol = self._resolve_symbol(instrument)
        if sl_pips <= 0:
            return self._volume_min(symbol)
        pv = self._pip_value_per_lot(symbol)
        vol = risk_usd / max(0.01, sl_pips * pv)
        step = self._volume_step(symbol)
        vol = max(self._volume_min(symbol), round(vol / step) * step)
        return round(min(vol, 1.0), 2)

    def place_market_order(self, instrument: str, direction: str, volume: float, stop_loss_pips: float, take_profit_pips: float, comment: str = "") -> Optional[Dict]:
        symbol = self._resolve_symbol(instrument)
        bid, ask = self.get_current_price(instrument)
        price = ask if direction == "BUY" else bid
        pip = self._pip_size(symbol)
        sl = price - stop_loss_pips * pip if direction == "BUY" else price + stop_loss_pips * pip
        tp = price + take_profit_pips * pip if direction == "BUY" else price - take_profit_pips * pip

        if not self.safe_to_trade:
            return {
                "broker_id": f"paper-{int(datetime.now(timezone.utc).timestamp())}",
                "instrument": symbol,
                "direction": direction,
                "volume": round(volume, 2),
                "entry_price": price,
                "stop_loss": sl,
                "take_profit": tp,
                "status": "paper",
            }

        info = self.mt5.symbol_info(symbol)
        if info is None:
            raise RuntimeError(f"Informations symbole indisponibles pour {symbol}")

        volume = round(max(self._volume_min(symbol), min(volume, 1.0)), 2)
        order_type = self.mt5.ORDER_TYPE_BUY if direction == "BUY" else self.mt5.ORDER_TYPE_SELL
        request = {
            "action": self.mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": volume,
            "type": order_type,
            "price": price,
            "sl": round(sl, info.digits),
            "tp": round(tp, info.digits),
            "deviation": MT5_DEVIATION,
            "magic": MT5_MAGIC_NUMBER,
            "comment": comment[:31],
            "type_time": self.mt5.ORDER_TIME_GTC,
            "type_filling": self.mt5.ORDER_FILLING_IOC,
        }
        result = self.mt5.order_send(request)
        if result is None or result.retcode not in {self.mt5.TRADE_RETCODE_DONE, self.mt5.TRADE_RETCODE_DONE_PARTIAL}:
            err = self.mt5.last_error() if result is None else result.retcode
            desc = self._describe_trade_retcode(err)
            raise RuntimeError(f"order_send échoué: {err} ({desc})")

        order_id = getattr(result, "order", None) or getattr(result, "deal", None)
        # Retrieve the position ticket (often == order, but not always)
        position_ticket = None
        try:
            positions = self.mt5.positions_get(symbol=symbol) or []
            for pos in positions:
                if getattr(pos, "ticket", None) == order_id:
                    position_ticket = order_id
                    break
            if position_ticket is None and positions:
                # Fallback: most recent position for this symbol
                position_ticket = getattr(positions[-1], "ticket", None)
        except Exception:
            pass

        return {
            "broker_id": order_id,
            "position_ticket": position_ticket or order_id,
            "instrument": symbol,
            "direction": direction,
            "units": volume,
            "entry_price": price,
            "stop_loss": sl,
            "take_profit": tp,
            "status": "open",
        }

    def modify_position(self, ticket: int, new_sl: float = None, new_tp: float = None) -> bool:
        self._ensure_ready()
        if not self.safe_to_trade:
            return False
        pos = None
        for p in (self.mt5.positions_get() or []):
            if getattr(p, 'ticket', None) == int(ticket):
                pos = p
                break
        if pos is None:
            return False
        symbol = pos.symbol
        info = self.mt5.symbol_info(symbol)
        digits = int(getattr(info, 'digits', 5) or 5)
        sl = round(float(new_sl), digits) if new_sl is not None else float(getattr(pos, 'sl', 0.0) or 0.0)
        tp = round(float(new_tp), digits) if new_tp is not None else float(getattr(pos, 'tp', 0.0) or 0.0)
        request = {
            'action': self.mt5.TRADE_ACTION_SLTP,
            'symbol': symbol,
            'position': int(ticket),
            'sl': sl,
            'tp': tp,
            'magic': MT5_MAGIC_NUMBER,
            'deviation': MT5_DEVIATION,
        }
        result = self.mt5.order_send(request)
        if result is None or result.retcode not in {self.mt5.TRADE_RETCODE_DONE, self.mt5.TRADE_RETCODE_DONE_PARTIAL}:
            err = self.mt5.last_error() if result is None else int(getattr(result, "retcode", 0) or 0)
            desc = self._describe_trade_retcode(err)
            print(f"[MT5Broker][WARN] modify_position échoué: {err} ({desc})")
            return False
        return True

    def modify_sl(self, ticket_or_instrument, new_sl: float) -> bool:
        """Modifie le SL d'une position (par ticket préféré, sinon instrument)."""
        self._ensure_ready()
        ticket = None

        if isinstance(ticket_or_instrument, (int, float)):
            ticket = int(ticket_or_instrument)
        else:
            raw = str(ticket_or_instrument).strip()
            if raw.isdigit():
                ticket = int(raw)

        if ticket is None:
            symbol = self._resolve_symbol(str(ticket_or_instrument))
            positions = self.mt5.positions_get(symbol=symbol) or []
            if not positions:
                return False
            ticket = int(getattr(positions[0], "ticket", 0) or 0)

        if ticket <= 0:
            return False

        # Retry x1 sur erreurs MT5 transitoires (requote, marché fermé, pas de connexion).
        attempts = 2
        for idx in range(attempts):
            ok = self.modify_position(ticket, new_sl=new_sl, new_tp=None)
            if ok:
                return True
            if idx == 0:
                print(f"[MT5Broker][WARN] modify_sl tentative 1 échouée (ticket={ticket})")

        print(f"[MT5Broker][WARN] modify_sl échec définitif (ticket={ticket})")
        return False

    def close_position(self, instrument: str) -> Optional[float]:
        positions = self.mt5.positions_get(symbol=symbol) or []
        if not positions:
            return 0.0

        total_profit = 0.0
        for pos in positions:
            total_profit += float(getattr(pos, "profit", 0.0))
            if not self.safe_to_trade:
                continue

            close_type = self.mt5.ORDER_TYPE_SELL if pos.type == self.mt5.POSITION_TYPE_BUY else self.mt5.ORDER_TYPE_BUY
            tick = self.mt5.symbol_info_tick(symbol)
            price = float(tick.bid if close_type == self.mt5.ORDER_TYPE_SELL else tick.ask)
            request = {
                "action": self.mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": float(getattr(pos, "volume", 0.0)),
                "type": close_type,
                "position": int(getattr(pos, "ticket", 0)),
                "price": price,
                "deviation": MT5_DEVIATION,
                "magic": MT5_MAGIC_NUMBER,
                "comment": "LOCAL-AUTO-CLOSE",
                "type_time": self.mt5.ORDER_TIME_GTC,
                "type_filling": self.mt5.ORDER_FILLING_IOC,
            }
            result = self.mt5.order_send(request)
            if result is None or result.retcode not in {self.mt5.TRADE_RETCODE_DONE, self.mt5.TRADE_RETCODE_DONE_PARTIAL}:
                err = self.mt5.last_error() if result is None else result.retcode
                desc = self._describe_trade_retcode(err)
                raise RuntimeError(f"close_position échoué: {err} ({desc})")

        return total_profit


def build_broker():
    if bool(PAPER_TRADING):
        return ExternalPaperBroker()

    target = (BROKER or "mt5").lower().strip()
    if target == "mt5":
        broker = MT5Broker()
        if broker.connected or broker.mt5 is not None:
            return broker
        return ExternalPaperBroker()
    return ExternalPaperBroker()
