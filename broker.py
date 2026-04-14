"""
Broker layer.
Priorité à MetaTrader 5 détecté localement avec compte Exness démo, sans API Exness.
"""

import math
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

try:
    import requests
except Exception:
    requests = None

from config import (
    BROKER, INITIAL_CAPITAL, OANDA_API_KEY, OANDA_ACCOUNT_ID, OANDA_ENV,
    MT5_TERMINAL_PATH, MT5_LOGIN, MT5_PASSWORD, MT5_SERVER, REQUIRE_DEMO_ACCOUNT,
    ALLOW_TRADE_EXECUTION, MT5_MAGIC_NUMBER, MT5_DEVIATION,
    MT5_USE_VISIBLE_SYMBOLS, MT5_MAX_VISIBLE_SYMBOLS, INSTRUMENTS,
    SYMBOL_SOURCE_MODE, PREFERRED_SYMBOLS
)
from runtime_store import RuntimeStore


class DemoBroker:
    def __init__(self, reason: str = "Mode démo local"):
        self.name = "demo"
        self.connected = False
        self.safe_to_trade = False
        self.last_error = reason
        self.status_message = reason

    def get_account_summary(self) -> Dict:
        return {
            "balance": INITIAL_CAPITAL,
            "unrealized_pnl": 0.0,
            "nav": INITIAL_CAPITAL,
            "open_trades": 0,
            "currency": "USD",
            "connected": False,
            "provider": "demo",
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

    def get_spread_pips(self, instrument: str) -> float:
        bid, ask = self.get_current_price(instrument)
        return (ask - bid) * (100 if "JPY" in instrument else 10000)

    def calculate_units(self, instrument: str, risk_usd: float, stop_loss_pips: float) -> int:
        if stop_loss_pips <= 0:
            return 1000
        return max(1000, min(int((risk_usd / stop_loss_pips) * 1000), 10000))

    def place_market_order(self, instrument: str, direction: str, units: int, stop_loss_pips: float, take_profit_pips: float, comment: str = "") -> Optional[Dict]:
        bid, ask = self.get_current_price(instrument)
        entry = ask if direction == "BUY" else bid
        pip = 0.01 if "JPY" in instrument else 0.0001
        return {
            "broker_id": f"paper-{int(datetime.utcnow().timestamp())}",
            "instrument": instrument,
            "direction": direction,
            "units": units,
            "entry_price": entry,
            "stop_loss": entry - stop_loss_pips * pip if direction == "BUY" else entry + stop_loss_pips * pip,
            "take_profit": entry + take_profit_pips * pip if direction == "BUY" else entry - take_profit_pips * pip,
            "status": "paper",
            "comment": comment,
        }

    def close_position(self, instrument: str) -> Optional[float]:
        return 0.0

    def get_active_symbols(self, fallback: Optional[List[str]] = None) -> List[str]:
        return list(fallback or INSTRUMENTS)


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
        self.safe_to_trade = bool(is_demo and ALLOW_TRADE_EXECUTION)
        server = getattr(account, "server", "")
        company = getattr(account, "company", "")
        login = getattr(account, "login", "")

        if REQUIRE_DEMO_ACCOUNT and not is_demo:
            self.status_message = f"Compte MT5 connecté ({server}) détecté en lecture seule, pas en démo."
        elif ALLOW_TRADE_EXECUTION and is_demo:
            self.status_message = f"Exness/MT5 démo détecté et prêt au trading: {login} @ {server}"
        else:
            self.status_message = f"Exness/MT5 détecté: {login} @ {server} ({company}) - mode analyse/paper"

    def _is_demo_account(self, account) -> bool:
        server = f"{getattr(account, 'server', '')} {getattr(account, 'company', '')}".lower()
        return "demo" in server or "trial" in server or getattr(account, "trade_mode", None) == 0

    def _ensure_ready(self):
        if not self.connected or self.mt5 is None:
            raise RuntimeError(self.last_error or "MT5 non connecté")

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

    def _pip_factor(self, symbol: str) -> int:
        return 100 if "JPY" in symbol.upper() else 10000

    def list_visible_symbols(self) -> List[str]:
        self._ensure_ready()
        symbols = self.mt5.symbols_get() or []
        visible = [getattr(sym, "name", "") for sym in symbols if getattr(sym, "visible", False)]
        return [name for name in visible if name]

    def get_active_symbols(self, fallback: Optional[List[str]] = None) -> List[str]:
        self._ensure_ready()
        settings = RuntimeStore().get_settings()
        positions = [getattr(pos, "symbol", "") for pos in (self.mt5.positions_get() or [])]
        visible = self.list_visible_symbols() if MT5_USE_VISIBLE_SYMBOLS else []

        preferred = []
        for raw in settings.get("preferred_symbols", PREFERRED_SYMBOLS):
            try:
                preferred.append(self._resolve_symbol(raw))
            except Exception:
                preferred.append(raw)

        mode = str(settings.get("symbol_source_mode", SYMBOL_SOURCE_MODE or "preferred")).lower()
        max_symbols = int(settings.get("max_symbols_per_cycle", MT5_MAX_VISIBLE_SYMBOLS))
        if mode == "preferred":
            source = preferred + positions
        elif mode == "visible":
            source = positions + visible
        else:
            source = preferred + positions + visible + list(fallback or INSTRUMENTS)

        ordered = []
        for name in source:
            if name and name not in ordered:
                ordered.append(name)

        if ordered:
            return ordered[:max_symbols]
        return list(fallback or INSTRUMENTS)

    def get_account_summary(self) -> Dict:
        self._ensure_ready()
        account = self.mt5.account_info()
        runtime = RuntimeStore().get_settings()
        is_demo = self._is_demo_account(account)
        self.safe_to_trade = bool(is_demo and runtime.get("allow_trade_execution", ALLOW_TRADE_EXECUTION))
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
                "instrument": pos.symbol,
                "direction": direction,
                "units": getattr(pos, "volume", 0.0),
                "unrealized_pnl": float(getattr(pos, "profit", 0.0)),
                "avg_price": float(getattr(pos, "price_open", 0.0)),
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
        return (ask - bid) * self._pip_factor(symbol)

    def calculate_units(self, instrument: str, risk_usd: float, stop_loss_pips: float) -> int:
        if stop_loss_pips <= 0:
            return 1000
        micro_lots = max(1, int(risk_usd / max(0.5, stop_loss_pips * 0.1)))
        return max(1000, min(micro_lots * 1000, 100000))

    def place_market_order(self, instrument: str, direction: str, units: int, stop_loss_pips: float, take_profit_pips: float, comment: str = "") -> Optional[Dict]:
        symbol = self._resolve_symbol(instrument)
        bid, ask = self.get_current_price(instrument)
        price = ask if direction == "BUY" else bid
        pip = 0.01 if "JPY" in symbol.upper() else 0.0001
        sl = price - stop_loss_pips * pip if direction == "BUY" else price + stop_loss_pips * pip
        tp = price + take_profit_pips * pip if direction == "BUY" else price - take_profit_pips * pip

        if not self.safe_to_trade:
            return {
                "broker_id": f"paper-{int(datetime.utcnow().timestamp())}",
                "instrument": symbol,
                "direction": direction,
                "units": units,
                "entry_price": price,
                "stop_loss": sl,
                "take_profit": tp,
                "status": "paper",
            }

        info = self.mt5.symbol_info(symbol)
        if info is None:
            raise RuntimeError(f"Informations symbole indisponibles pour {symbol}")

        volume = round(max(0.01, min(units / 100000, 1.0)), 2)
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
            raise RuntimeError(f"order_send échoué: {err}")

        return {
            "broker_id": getattr(result, "order", None) or getattr(result, "deal", None),
            "instrument": symbol,
            "direction": direction,
            "units": units,
            "entry_price": price,
            "stop_loss": sl,
            "take_profit": tp,
            "status": "open",
        }

    def close_position(self, instrument: str) -> Optional[float]:
        return None


class OandaBroker:
    def __init__(self):
        self.name = "oanda"
        self.connected = False
        self.safe_to_trade = False
        self.last_error = ""
        self.status_message = "Broker OANDA en secours"

        if OANDA_ENV == "practice":
            self.base_url = "https://api-fxpractice.oanda.com/v3"
        else:
            self.base_url = "https://api-fxtrade.oanda.com/v3"
        self.headers = {
            "Authorization": f"Bearer {OANDA_API_KEY}",
            "Content-Type": "application/json",
        }
        self.connected = bool(OANDA_API_KEY and OANDA_ACCOUNT_ID and requests is not None)
        if not self.connected:
            self.last_error = "OANDA non configuré ou package requests absent"

    def _ensure_requests(self):
        if requests is None:
            raise RuntimeError("package requests absent")

    def _get(self, endpoint: str, params: Dict = None) -> Dict:
        self._ensure_requests()
        url = f"{self.base_url}{endpoint}"
        response = requests.get(url, headers=self.headers, params=params, timeout=10)
        response.raise_for_status()
        return response.json()

    def _post(self, endpoint: str, data: Dict) -> Dict:
        self._ensure_requests()
        url = f"{self.base_url}{endpoint}"
        response = requests.post(url, headers=self.headers, json=data, timeout=10)
        response.raise_for_status()
        return response.json()

    def get_account_summary(self) -> Dict:
        data = self._get(f"/accounts/{OANDA_ACCOUNT_ID}/summary")
        acc = data["account"]
        return {
            "balance": float(acc["balance"]),
            "unrealized_pnl": float(acc["unrealizedPL"]),
            "nav": float(acc["NAV"]),
            "open_trades": int(acc["openTradeCount"]),
            "currency": acc["currency"],
            "connected": True,
            "provider": "oanda",
        }

    def get_open_positions(self) -> List[Dict]:
        data = self._get(f"/accounts/{OANDA_ACCOUNT_ID}/openPositions")
        positions = []
        for pos in data.get("positions", []):
            for side, label in [("long", "BUY"), ("short", "SELL")]:
                units = float(pos.get(side, {}).get("units", 0))
                if units != 0:
                    positions.append({
                        "instrument": pos["instrument"],
                        "direction": label,
                        "units": abs(units),
                        "unrealized_pnl": float(pos.get(side, {}).get("unrealizedPL", 0)),
                        "avg_price": float(pos.get(side, {}).get("averagePrice", 0)),
                    })
        return positions

    def get_candles(self, instrument: str, granularity: str = "H1", count: int = 100) -> List[Dict]:
        data = self._get(f"/instruments/{instrument}/candles", {"granularity": granularity, "count": count, "price": "MBA"})
        candles = []
        for row in data.get("candles", []):
            if row.get("complete"):
                mid = row.get("mid", {})
                candles.append({
                    "time": row["time"],
                    "open": float(mid.get("o", 0)),
                    "high": float(mid.get("h", 0)),
                    "low": float(mid.get("l", 0)),
                    "close": float(mid.get("c", 0)),
                    "volume": int(row.get("volume", 0)),
                })
        return candles

    def get_current_price(self, instrument: str) -> Tuple[float, float]:
        data = self._get(f"/accounts/{OANDA_ACCOUNT_ID}/pricing", {"instruments": instrument})
        price = data["prices"][0]
        return float(price["bids"][0]["price"]), float(price["asks"][0]["price"])

    def get_spread_pips(self, instrument: str) -> float:
        bid, ask = self.get_current_price(instrument)
        return (ask - bid) * (100 if "JPY" in instrument else 10000)

    def calculate_units(self, instrument: str, risk_usd: float, stop_loss_pips: float) -> int:
        if stop_loss_pips <= 0:
            return 1000
        pip_value = 0.01 if "JPY" in instrument else 0.0001
        units = int(risk_usd / max(0.00001, stop_loss_pips * pip_value))
        return max(1000, min(units, 10000))

    def place_market_order(self, instrument: str, direction: str, units: int, stop_loss_pips: float, take_profit_pips: float, comment: str = "") -> Optional[Dict]:
        bid, ask = self.get_current_price(instrument)
        entry = ask if direction == "BUY" else bid
        pip = 0.01 if "JPY" in instrument else 0.0001
        sl = entry - stop_loss_pips * pip if direction == "BUY" else entry + stop_loss_pips * pip
        tp = entry + take_profit_pips * pip if direction == "BUY" else entry - take_profit_pips * pip
        actual_units = units if direction == "BUY" else -units
        data = {
            "order": {
                "type": "MARKET",
                "instrument": instrument,
                "units": str(actual_units),
                "stopLossOnFill": {"price": f"{sl:.5f}"},
                "takeProfitOnFill": {"price": f"{tp:.5f}"},
                "clientExtensions": {"comment": comment[:64]},
            }
        }
        result = self._post(f"/accounts/{OANDA_ACCOUNT_ID}/orders", data)
        fill = result.get("orderFillTransaction", {})
        return {
            "broker_id": fill.get("id"),
            "instrument": instrument,
            "direction": direction,
            "units": units,
            "entry_price": float(fill.get("price", entry)),
            "stop_loss": sl,
            "take_profit": tp,
            "status": "open",
        }

    def close_position(self, instrument: str) -> Optional[float]:
        data = self._post(f"/accounts/{OANDA_ACCOUNT_ID}/positions/{instrument}/close", {"longUnits": "ALL", "shortUnits": "ALL"})
        pnl = 0.0
        for key in ["longOrderFillTransaction", "shortOrderFillTransaction"]:
            if key in data:
                pnl += float(data[key].get("pl", 0))
        return pnl

    def get_active_symbols(self, fallback: Optional[List[str]] = None) -> List[str]:
        return list(fallback or INSTRUMENTS)


def build_broker():
    target = (BROKER or "mt5").lower().strip()
    if target == "mt5":
        broker = MT5Broker()
        if broker.connected or broker.mt5 is not None:
            return broker
        return DemoBroker(broker.last_error or "MT5 non disponible")
    if target == "oanda":
        broker = OandaBroker()
        if broker.connected:
            return broker
        return DemoBroker(broker.last_error or "OANDA non disponible")
    return DemoBroker("Mode démo forcé")
