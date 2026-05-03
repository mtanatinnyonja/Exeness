import pytest, math, random
from signal_engine import calculate_rsi, calculate_atr, calculate_bollinger, calculate_macd, calculate_signal_score
from signal_engine import (
    calculate_adx,
    calculate_support_resistance,
    detect_candle_pattern,
    calculate_price_momentum,
    calculate_trend_strength,
    detect_market_regime,
    calculate_volume_filter,
    calculate_obv,
    build_human_analysis_summary,
    build_price_action_description,
    calculate_mtf_signal,
)


def make_candles(n=100, start=1.08500, trend=0.0, volatility=0.0005):
    """Genere n bougies synthetiques realistes."""
    candles = []
    price = start
    for i in range(n):
        price += trend + random.gauss(0, volatility)
        price = max(price, 0.001)
        high = price + abs(random.gauss(0, volatility))
        low = price - abs(random.gauss(0, volatility))
        candles.append(
            {
                "open": price - trend / 2,
                "high": high,
                "low": low,
                "close": price,
                "tick_volume": random.randint(100, 1000),
            }
        )
    return candles


@pytest.fixture(autouse=True)
def _seed_random():
    random.seed(42)


# ---------------------------------------------------------------------------
# calculate_rsi
# ---------------------------------------------------------------------------

def test_rsi_constant_closes_is_50():
    closes = [1.0] * 50
    rsi = calculate_rsi(closes)
    assert math.isclose(rsi, 50.0, abs_tol=1e-9)


def test_rsi_consecutive_ups_is_over_70():
    closes = [1.0 + i * 0.001 for i in range(50)]
    rsi = calculate_rsi(closes)
    assert rsi > 70


def test_rsi_consecutive_downs_is_under_30():
    closes = [2.0 - i * 0.001 for i in range(50)]
    rsi = calculate_rsi(closes)
    assert rsi < 30


def test_rsi_insufficient_data_returns_50_exact():
    closes = [1.0] * 28
    assert calculate_rsi(closes) == 50.0


def test_rsi_always_between_0_and_100():
    closes = [1.0 + random.gauss(0, 0.01) for _ in range(60)]
    rsi = calculate_rsi(closes)
    assert 0.0 <= rsi <= 100.0


# ---------------------------------------------------------------------------
# calculate_bollinger
# ---------------------------------------------------------------------------

def test_bollinger_order_upper_middle_lower():
    closes = [1.0 + random.gauss(0, 0.01) for _ in range(80)]
    upper, middle, lower = calculate_bollinger(closes, period=20, std_mult=2.0)
    assert upper > middle > lower


def test_bollinger_identical_closes_all_equal():
    closes = [1.2345] * 40
    upper, middle, lower = calculate_bollinger(closes, period=20, std_mult=2.0)
    assert upper == middle == lower == 1.2345


def test_bollinger_insufficient_data_returns_last_close_triplet():
    closes = [1.1111, 1.2222, 1.3333]
    upper, middle, lower = calculate_bollinger(closes, period=20, std_mult=2.0)
    assert (upper, middle, lower) == (closes[-1], closes[-1], closes[-1])


# ---------------------------------------------------------------------------
# calculate_atr
# ---------------------------------------------------------------------------

def test_atr_insufficient_data_returns_zero():
    candles = make_candles(n=10)
    assert calculate_atr(candles, period=14) == 0.0


def test_atr_always_non_negative():
    candles = make_candles(n=120)
    atr = calculate_atr(candles, period=14)
    assert atr >= 0.0


def test_atr_volatile_greater_than_stable():
    stable = make_candles(n=160, volatility=0.00005)
    volatile = make_candles(n=160, volatility=0.002)
    atr_stable = calculate_atr(stable, period=14)
    atr_volatile = calculate_atr(volatile, period=14)
    assert atr_volatile > atr_stable


# ---------------------------------------------------------------------------
# calculate_macd
# ---------------------------------------------------------------------------

def test_macd_insufficient_data_returns_zero_tuple():
    closes = [1.0 + random.gauss(0, 0.001) for _ in range(20)]
    macd, signal = calculate_macd(closes)
    assert macd == 0.0 and signal == 0.0


def test_macd_returns_numeric_values_with_enough_data():
    closes = [1.0 + (i * 0.0005) + random.gauss(0, 0.0001) for i in range(120)]
    macd, signal = calculate_macd(closes)
    assert isinstance(macd, float)
    assert isinstance(signal, float)


# ---------------------------------------------------------------------------
# calculate_signal_score
# ---------------------------------------------------------------------------

def test_signal_score_insufficient_candles_returns_zero_and_none_direction():
    candles = make_candles(n=40)
    result = calculate_signal_score(candles, "XAUUSDm")
    assert result["score"] == 0
    assert result["direction"] is None


def test_signal_score_range_and_direction_domain_and_required_details():
    candles = make_candles(n=220, trend=0.00005, volatility=0.0002)
    result = calculate_signal_score(candles, "XAUUSDm")

    assert 0 <= result["score"] <= 5
    assert result["direction"] in (None, "BUY", "SELL")

    details = result.get("details", {})
    assert "rsi" in details
    assert "atr_pips" in details
    assert "quality_score" in details
    assert 0.0 <= float(details["quality_score"]) <= 1.5


def test_signal_score_strong_bullish_trend_gives_buy():
    candles = make_candles(n=240, trend=0.0003, volatility=0.00005)
    result = calculate_signal_score(candles, "XAUUSDm")
    assert result["direction"] == "BUY"


def test_signal_score_strong_bearish_trend_gives_sell():
    candles = make_candles(n=240, trend=-0.0003, volatility=0.00005)
    result = calculate_signal_score(candles, "XAUUSDm")
    assert result["direction"] == "SELL"


# ---------------------------------------------------------------------------
# Coverage helpers
# ---------------------------------------------------------------------------

def test_adx_returns_non_negative_with_enough_data():
    candles = make_candles(n=80, trend=0.0001, volatility=0.0002)
    adx = calculate_adx(candles, period=14)
    assert adx >= 0.0


def test_support_resistance_returns_valid_levels():
    candles = make_candles(n=120, trend=0.00002, volatility=0.0003)
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    resistance, support = calculate_support_resistance(highs, lows, window=40)
    assert resistance >= support


def test_detect_candle_pattern_hammer_and_bearish_engulfing():
    hammer_series = [
        {"open": 1.0, "high": 1.01, "low": 0.99, "close": 1.005, "tick_volume": 100},
        {"open": 1.005, "high": 1.006, "low": 0.995, "close": 1.0048, "tick_volume": 100},
    ]
    assert detect_candle_pattern(hammer_series) in {"hammer", "doji", None}

    engulf_series = [
        {"open": 1.1, "high": 1.101, "low": 1.095, "close": 1.1005, "tick_volume": 100},
        {"open": 1.101, "high": 1.102, "low": 1.094, "close": 1.095, "tick_volume": 120},
    ]
    assert detect_candle_pattern(engulf_series) in {"bearish_engulfing", "shooting_star", None}


def test_momentum_and_trend_strength_signs():
    up_closes = [1.0 + i * 0.001 for i in range(40)]
    down_closes = [2.0 - i * 0.001 for i in range(40)]
    assert calculate_price_momentum(up_closes, lookback=10) > 0
    assert calculate_price_momentum(down_closes, lookback=10) < 0
    assert calculate_trend_strength(up_closes, period=20) >= 0.0


def test_detect_market_regime_outputs_known_labels():
    label = detect_market_regime(1.2, 0.0005, 1.201, 1.2)
    assert label in {"unknown", "volatile", "range", "trend_bullish", "trend_bearish"}


def test_volume_filter_and_obv_neutral_when_no_volume():
    candles = [{"open": 1.0, "high": 1.1, "low": 0.9, "close": 1.0, "tick_volume": 0} for _ in range(40)]
    vol = calculate_volume_filter(candles)
    obv = calculate_obv(candles)
    assert vol["volume_signal"] in {"absent", "faible"}
    assert obv == "neutre"


def test_human_summary_returns_string():
    details = {"market_regime": "range", "rsi": 50, "rr_buy": 1.2, "rr_sell": 1.1, "signal_bias": 0.0, "mtf_confirmed": False}
    summary = build_human_analysis_summary(details, "BUY", 3)
    assert isinstance(summary, str)
    assert len(summary) > 10


def test_price_action_description_returns_text():
    candles = make_candles(n=90, trend=0.00005, volatility=0.0002)
    text = build_price_action_description(candles, "XAUUSDm")
    assert isinstance(text, str)
    assert "Support:" in text or "Structure:" in text


def test_mtf_signal_branches_no_d1_aligned_and_counter():
    h1_up = make_candles(n=220, trend=0.00025, volatility=0.00005)
    d1_up = make_candles(n=220, trend=0.0002, volatility=0.00005)
    d1_down = make_candles(n=220, trend=-0.0002, volatility=0.00005)

    no_d1 = calculate_mtf_signal(h1_up, [], "XAUUSDm")
    assert no_d1.get("confluence") == "no_d1_data"

    aligned = calculate_mtf_signal(h1_up, d1_up, "XAUUSDm")
    assert aligned.get("confluence") in {"aligned", "neutral", "counter"}

    counter = calculate_mtf_signal(h1_up, d1_down, "XAUUSDm")
    assert counter.get("confluence") in {"aligned", "neutral", "counter", "counter_d1_blocked"}
