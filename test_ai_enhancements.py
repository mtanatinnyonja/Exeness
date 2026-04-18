"""
Tests unitaires pour les nouvelles fonctionnalités IA: filtrage de signal et contexte marché.
"""

from datetime import datetime, timezone, timedelta

from market_context import analyze_market_context
from signal_filter import filter_signal_quality


class DummyMemory:
    def __init__(self, trades):
        self.trades = trades

    def get_trades_started_today(self):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return sum(1 for trade in self.trades if str(trade.get("timestamp", "")).startswith(today))


def check(name, condition, detail=""):
    print(f"✅ {name}" if condition else f"❌ {name} — {detail}")
    return condition


def build_candle(close, prev_close=0.0):
    high = max(close, prev_close) + 0.05
    low = min(close, prev_close) - 0.05
    return {"open": prev_close, "high": high, "low": low, "close": close}


def test_market_context():
    # Trend : hausse continue
    candles = [build_candle(100 + i * 0.2, 100 + (i - 1) * 0.2) for i in range(60)]
    ctx = analyze_market_context(candles, "EURUSDm")
    check("Market context détecte trend", ctx["category"] == "trend", str(ctx))

    # Range : petites variations avec ATR faible
    candles = [build_candle(100 + ((-1) ** i) * 0.01, 100 + ((-1) ** (i - 1)) * 0.01) for i in range(60)]
    ctx = analyze_market_context(candles, "EURUSDm")
    check("Market context détecte range", ctx["category"] == "range", str(ctx))

    # Indéterminé
    mixed = [build_candle(100 + ((i % 4) - 2) * 0.8, 100 + (((i - 1) % 4) - 2) * 0.8) for i in range(60)]
    ctx = analyze_market_context(mixed, "EURUSDm")
    check("Market context détecte uncertain", ctx["category"] == "uncertain", str(ctx))


def test_signal_filter():
    memory = DummyMemory([])
    config = {
        "min_signal_score": 3,
        "min_signal_bias": 0.5,
        "max_open_positions": 2,
        "max_trades_per_day": 4,
        "trade_cooldown_minutes": 15,
    }

    signal = {"score": 2, "direction": "BUY", "details": {"signal_bias": 0.7}}
    result = filter_signal_quality(signal, None, {"category": "trend"}, 0, memory, config)
    check("Signal low score bloque", result["blocked"], str(result))

    signal = {"score": 3, "direction": "BUY", "details": {"signal_bias": 0.2}}
    result = filter_signal_quality(signal, None, {"category": "uncertain"}, 0, memory, config)
    check("Signal incertain bloque si biais faible", result["blocked"], str(result))

    signal = {"score": 4, "direction": "SELL", "details": {"signal_bias": 1.0}}
    confirm = {"score": 3, "direction": "BUY"}
    result = filter_signal_quality(signal, confirm, {"category": "trend"}, 0, memory, config)
    check("Conflit de TF bloque", result["blocked"], str(result))

    trades = [
        {"timestamp": datetime.now(timezone.utc).isoformat()},
        {"timestamp": datetime.now(timezone.utc).isoformat()},
        {"timestamp": datetime.now(timezone.utc).isoformat()},
        {"timestamp": datetime.now(timezone.utc).isoformat()},
    ]
    memory = DummyMemory(trades)
    signal = {"score": 5, "direction": "BUY", "details": {"signal_bias": 1.0}}
    result = filter_signal_quality(signal, None, {"category": "trend"}, 0, memory, config)
    check("Plafond de trades journaliers bloque", result["blocked"], str(result))


def run_all():
    print("\n=== test_ai_enhancements ===")
    test_market_context()
    test_signal_filter()
    print("\nTests terminés.")


if __name__ == "__main__":
    run_all()
