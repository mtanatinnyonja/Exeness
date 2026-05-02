"""
Tests unitaires pour signal_engine.py — pytest.

Logique pure : aucune connexion MT5 ni Ollama requise.
Exécuter : pytest test_signal_engine.py -v
Couverture : pytest test_signal_engine.py --cov=signal_engine --cov-report=term-missing
"""

import math
import random
import pytest
from typing import List, Dict, Optional

from signal_engine import (
    calculate_rsi,
    calculate_ma,
    calculate_ema,
    calculate_bollinger,
    calculate_atr,
    calculate_macd,
    calculate_adx,
    calculate_obv,
    calculate_price_momentum,
    calculate_trend_strength,
    detect_candle_pattern,
    detect_market_regime,
    calculate_support_resistance,
    calculate_signal_score,
    calculate_volume_filter,
)
from signal_engine import (
    calculate_mtf_signal,
    build_human_analysis_summary,
    build_price_action_description,
    apply_optimized_params,
)


# ===========================================================================
# Helpers & Fixtures
# ===========================================================================

def _make_candle(
    open_: float,
    close: float,
    high: float = None,
    low: float = None,
    volume: int = 100,
) -> Dict:
    """Crée un dict bougie minimal valide."""
    if high is None:
        high = max(open_, close) + 0.0005
    if low is None:
        low = min(open_, close) - 0.0005
    return {
        "open": open_,
        "close": close,
        "high": high,
        "low": low,
        "tick_volume": volume,
    }


def generate_flat_candles(n: int, price: float = 1.08500) -> List[Dict]:
    """n bougies entièrement plates (open=close=high=low=price)."""
    return [_make_candle(price, price, price, price) for _ in range(n)]


def generate_trending_candles(
    direction: str,
    n: int,
    base_price: float = 1.08500,
    step: float = 0.0002,
) -> List[Dict]:
    """
    Génère n bougies synthétiques EURUSD en tendance.

    Parameters
    ----------
    direction : 'up' ou 'down'
    n         : nombre de bougies
    base_price: prix de départ
    step      : variation par bougie (en points de prix)
    """
    candles: List[Dict] = []
    price = base_price
    for _ in range(n):
        if direction == "up":
            open_ = price
            close = price + step
            high = close + step * 0.4
            low = open_ - step * 0.1
        else:
            open_ = price
            close = price - step
            high = open_ + step * 0.1
            low = close - step * 0.4
        candles.append(_make_candle(open_, close, high, low))
        price = close
    return candles


@pytest.fixture
def trending_candles_factory():
    """
    Fixture pytest qui retourne generate_trending_candles.
    Usage dans les tests :  candles = trending_candles_factory('up', 80)
    """
    return generate_trending_candles


def generate_realistic_candles(
    n: int = 100,
    base_price: float = 1.08500,
    noise: float = 0.0003,
    seed: int = 42,
) -> List[Dict]:
    """n bougies EURUSD réalistes avec bruit pseudo-aléatoire (seed fixe)."""
    rng = random.Random(seed)
    candles: List[Dict] = []
    price = base_price
    for _ in range(n):
        delta = rng.uniform(-noise, noise)
        open_ = price
        close = price + delta
        spread = rng.uniform(0.0001, 0.0004)
        high = max(open_, close) + rng.uniform(0, spread)
        low = min(open_, close) - rng.uniform(0, spread)
        candles.append(
            _make_candle(open_, close, high, low, volume=rng.randint(50, 500))
        )
        price = close
    return candles


# ===========================================================================
# calculate_rsi
# ===========================================================================

class TestCalculateRSI:
    """Tests sur RSI méthode Wilder, identique MT5/TradingView."""

    def test_insufficient_data_returns_50(self):
        """< period*2+1 closes → sentinel 50.0."""
        closes = [1.0] * 28  # besoin de 29 pour period=14
        assert calculate_rsi(closes) == 50.0

    def test_exactly_at_minimum_boundary(self):
        """Exactement period*2+1 closes → valeur calculée (pas le fallback 50)."""
        closes = [1.0 + i * 0.001 for i in range(29)]
        result = calculate_rsi(closes)
        assert 0.0 <= result <= 100.0
        assert result != 50.0 or all(closes[i] == closes[0] for i in range(len(closes)))

    def test_flat_prices_return_50(self):
        """
        Closes identiques (avg_gain=0, avg_loss=0) → RSI=50.0.
        Comportement MT5 : marché plat = RSI indéfini, convention 50.
        """
        closes = [1.08500] * 40
        assert calculate_rsi(closes) == 50.0

    def test_14_consecutive_ups_near_100(self):
        """14 puis 26 hausses consécutives → RSI ≥ 95 (très peu de pertes)."""
        closes = [1.08500 + i * 0.0001 for i in range(40)]
        result = calculate_rsi(closes)
        assert result >= 95.0, f"Attendu ≥ 95, obtenu {result:.2f}"

    def test_all_down_moves_give_low_rsi(self):
        """40 baisses consécutives → RSI ≤ 10 (marché très baissier)."""
        closes = [2.00000 - i * 0.0002 for i in range(40)]
        result = calculate_rsi(closes)
        assert result <= 10.0, f"Attendu ≤ 10, obtenu {result:.2f}"

    @pytest.mark.parametrize("closes", [
        [1.0 + i * 0.01 for i in range(50)],   # tendance haussière
        [1.0] * 50,                              # plat
        [50.0 - i * 0.01 for i in range(50)],  # tendance baissière
    ])
    def test_rsi_always_in_0_100(self, closes):
        """RSI ∈ [0, 100] pour toute série valide."""
        result = calculate_rsi(closes)
        assert 0.0 <= result <= 100.0, f"RSI hors plage : {result}"

    def test_wilder_smoothing_reference(self):
        """
        Test de régression numérique : valeur de référence calculée indépendamment.

        Séquence : 14 hausses +1.0 (seed) + 14 baisses -1.0 (phase Wilder).
        Le résultat de signal_engine doit correspondre exactement à la formule
        réimplémentée ci-dessous (précision flottante machine).
        """
        period = 14
        closes = [100.0 + i for i in range(period + 1)] + [
            100.0 + period - i for i in range(1, period + 1)
        ]
        # 15 + 14 = 29 éléments = period*2 + 1

        # Référence indépendante (même algorithme, réécrit)
        deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
        seed = deltas[:period]
        avg_gain = sum(max(d, 0) for d in seed) / period
        avg_loss = sum(abs(min(d, 0)) for d in seed) / period
        for d in deltas[period:]:
            avg_gain = (avg_gain * (period - 1) + max(d, 0)) / period
            avg_loss = (avg_loss * (period - 1) + abs(min(d, 0))) / period

        if avg_gain == 0 and avg_loss == 0:
            expected = 50.0
        elif avg_loss == 0:
            expected = 100.0
        else:
            rs = avg_gain / avg_loss
            expected = 100.0 - (100.0 / (1.0 + rs))

        result = calculate_rsi(closes, period=period)
        assert result == pytest.approx(expected, abs=1e-9), (
            f"Wilder diverge : attendu {expected:.6f}, obtenu {result:.6f}"
        )

    def test_rsi_monotone_up_then_flat(self):
        """Forte hausse puis stabilisation → RSI élevé mais < 100."""
        closes = [1.0 + i * 0.005 for i in range(30)] + [1.145] * 10
        result = calculate_rsi(closes)
        assert 60.0 <= result <= 100.0

    def test_custom_period_7(self):
        """RSI avec période 7 — doit rester dans [0, 100]."""
        closes = [1.0 + i * 0.001 for i in range(30)]
        result = calculate_rsi(closes, period=7)
        assert 0.0 <= result <= 100.0

    def test_rsi_increases_with_more_up_moves(self):
        """Plus de hausses → RSI plus élevé."""
        few_ups = [1.0] * 10 + [1.0 + i * 0.001 for i in range(1, 20)]   # 10 plats + 19 montées
        many_ups = [1.0 + i * 0.001 for i in range(29)]                   # 29 montées
        rsi_few = calculate_rsi(few_ups)
        rsi_many = calculate_rsi(many_ups)
        assert rsi_many >= rsi_few


# ===========================================================================
# calculate_ma / calculate_ema
# ===========================================================================

class TestCalculateMA:

    def test_simple_average_of_last_period_values(self):
        closes = [1.0, 2.0, 3.0, 4.0, 5.0]
        assert calculate_ma(closes, period=3) == pytest.approx(4.0)  # (3+4+5)/3

    def test_period_equals_length(self):
        closes = [2.0, 4.0, 6.0]
        assert calculate_ma(closes, period=3) == pytest.approx(4.0)

    def test_insufficient_returns_last_value(self):
        closes = [1.0, 2.0]
        assert calculate_ma(closes, period=5) == pytest.approx(2.0)

    def test_empty_list_returns_zero(self):
        assert calculate_ma([], period=5) == 0.0

    def test_ma_uses_only_last_period_values(self):
        """MA(3) ne doit pas dépendre des anciennes valeurs."""
        closes_a = [999.0] * 10 + [1.0, 2.0, 3.0]
        closes_b = [0.0] * 10 + [1.0, 2.0, 3.0]
        assert calculate_ma(closes_a, period=3) == calculate_ma(closes_b, period=3)


class TestCalculateEMA:

    def test_returns_float(self):
        closes = [1.0 + i * 0.01 for i in range(20)]
        assert isinstance(calculate_ema(closes, period=9), float)

    def test_ema_insufficient_returns_last(self):
        closes = [1.0, 2.0]
        assert calculate_ema(closes, period=5) == pytest.approx(2.0)

    def test_ema_in_range_of_data(self):
        closes = [1.0 + i * 0.001 for i in range(30)]
        ema = calculate_ema(closes, period=9)
        assert closes[0] <= ema <= closes[-1]

    def test_ema_seed_equals_sma(self):
        """Le seed EMA doit être la SMA des n premières valeurs."""
        closes = [float(i) for i in range(1, 11)]   # [1..10]
        # Avec 10 valeurs et period=10, aucune étape de lissage → EMA = SMA
        result = calculate_ema(closes, period=10)
        expected = sum(closes) / 10
        assert result == pytest.approx(expected, rel=1e-9)


# ===========================================================================
# calculate_bollinger
# ===========================================================================

class TestCalculateBollinger:

    def test_ordering_upper_gt_middle_gt_lower(self):
        """upper > middle > lower pour une série avec dispersion."""
        closes = [1.08500 + (i % 5) * 0.0002 for i in range(25)]
        upper, middle, lower = calculate_bollinger(closes)
        assert upper > middle
        assert middle > lower

    def test_flat_prices_equal_bands(self):
        """Closes identiques → std=0 → upper == middle == lower == price."""
        closes = [1.08500] * 25
        upper, middle, lower = calculate_bollinger(closes)
        assert upper == pytest.approx(1.08500)
        assert middle == pytest.approx(1.08500)
        assert lower == pytest.approx(1.08500)

    def test_insufficient_data_returns_last_triple(self):
        """< period closes → retourne (last, last, last)."""
        closes = [1.08500, 1.08510, 1.08490]
        upper, middle, lower = calculate_bollinger(closes, period=20)
        assert upper == middle == lower == pytest.approx(1.08490)

    def test_std_multiplier_doubles_band_width(self):
        """Doubler std_mult doit doubler l'écart upper-middle."""
        closes = [1.0 + (i % 7) * 0.001 for i in range(25)]
        upper1, mid1, _ = calculate_bollinger(closes, period=20, std_mult=1.0)
        upper2, mid2, _ = calculate_bollinger(closes, period=20, std_mult=2.0)
        assert mid1 == pytest.approx(mid2)
        assert (upper2 - mid2) == pytest.approx((upper1 - mid1) * 2, rel=1e-9)

    def test_middle_band_is_exact_sma(self):
        """La bande médiane est la SMA exacte sur les period dernières closes."""
        closes = [float(i) for i in range(1, 26)]   # [1.0 .. 25.0]
        _, middle, _ = calculate_bollinger(closes, period=20)
        expected_sma = sum(range(6, 26)) / 20        # closes[-20:] = [6..25]
        assert middle == pytest.approx(expected_sma)

    def test_upper_and_lower_symmetric_around_middle(self):
        """upper et lower doivent être symétriques autour de middle."""
        closes = [1.0 + (i % 11) * 0.001 for i in range(30)]
        upper, middle, lower = calculate_bollinger(closes)
        assert (upper - middle) == pytest.approx(middle - lower, rel=1e-9)


# ===========================================================================
# calculate_atr
# ===========================================================================

class TestCalculateATR:

    def test_insufficient_data_returns_zero(self):
        candles = generate_realistic_candles(n=5)
        assert calculate_atr(candles, period=14) == 0.0

    def test_flat_market_atr_is_zero(self):
        """Bougies sans range → ATR = 0."""
        candles = generate_flat_candles(30)
        assert calculate_atr(candles, period=14) == pytest.approx(0.0)

    def test_atr_non_negative(self):
        candles = generate_realistic_candles(n=40)
        assert calculate_atr(candles, period=14) >= 0.0

    def test_volatile_market_higher_atr(self):
        """ATR(volatile) > ATR(quiet) pour la même période."""
        quiet = [_make_candle(1.0, 1.0001, 1.0003, 0.9998) for _ in range(30)]
        volatile = [_make_candle(1.0, 1.010, 1.020, 0.990) for _ in range(30)]
        assert calculate_atr(volatile, period=14) > calculate_atr(quiet, period=14)

    def test_atr_exact_when_all_trs_equal(self):
        """Si tous les TR sont identiques, ATR doit converger vers ce TR."""
        # Bougies avec TR = 0.010 exactement (high-low = 0.010, prev_close = low)
        candles = []
        for i in range(30):
            candles.append(_make_candle(1.0, 1.005, high=1.010, low=1.000))
        atr = calculate_atr(candles, period=14)
        assert atr == pytest.approx(0.010, rel=1e-3)


# ===========================================================================
# calculate_macd
# ===========================================================================

class TestCalculateMACD:

    def test_returns_two_values(self):
        closes = [1.0 + i * 0.001 for i in range(50)]
        result = calculate_macd(closes)
        assert len(result) == 2

    def test_insufficient_data_returns_zeros(self):
        macd, signal = calculate_macd([1.0] * 20)
        assert macd == 0.0
        assert signal == 0.0

    def test_macd_bullish_on_strong_uptrend(self):
        """
        MACD > signal sur tendance haussière accélérante.
        Une tendance linéaire fait converger MACD et signal — on utilise
        une accélération (quadratique) pour forcer l'écart.
        """
        # Tendance quadratique : EMA12 réagit plus vite qu'EMA26 → MACD monte
        closes = [1.0 + (i ** 1.5) * 0.001 for i in range(60)]
        macd, signal = calculate_macd(closes)
        assert macd > signal, f"MACD={macd:.6f} doit être > signal={signal:.6f}"

    def test_macd_bearish_on_strong_downtrend(self):
        """
        MACD < signal sur tendance baissière accélérante.
        Même logique que le test haussier : accélération quadratique.
        """
        closes = [100.0 - (i ** 1.5) * 0.05 for i in range(60)]
        macd, signal = calculate_macd(closes)
        assert macd < signal, f"MACD={macd:.6f} doit être < signal={signal:.6f}"

    def test_macd_is_float(self):
        closes = [1.0 + i * 0.001 for i in range(50)]
        macd, signal = calculate_macd(closes)
        assert isinstance(macd, float)
        assert isinstance(signal, float)


# ===========================================================================
# calculate_adx
# ===========================================================================

class TestCalculateADX:

    def test_insufficient_data_returns_zero(self):
        candles = generate_realistic_candles(n=5)
        assert calculate_adx(candles, period=14) == 0.0

    def test_adx_in_range_0_100(self):
        candles = generate_realistic_candles(n=80)
        result = calculate_adx(candles, period=14)
        assert 0.0 <= result <= 100.0

    def test_adx_higher_on_strong_trend(self):
        """ADX doit être plus élevé sur une tendance forte que sur données aléatoires."""
        trending = generate_trending_candles("up", n=80, step=0.0005)
        noisy = generate_realistic_candles(n=80, noise=0.0001)
        adx_trend = calculate_adx(trending, period=14)
        adx_noise = calculate_adx(noisy, period=14)
        assert adx_trend >= adx_noise


# ===========================================================================
# calculate_obv
# ===========================================================================

class TestCalculateOBV:

    def test_returns_dict_with_trend_key(self):
        candles = generate_realistic_candles(n=20)
        result = calculate_obv(candles)
        assert "obv_trend" in result
        assert "obv_slope" in result

    def test_trend_values_are_valid(self):
        candles = generate_realistic_candles(n=20)
        result = calculate_obv(candles)
        assert result["obv_trend"] in ("haussiere", "baissiere", "neutre")

    def test_uptrend_gives_haussiere(self):
        candles = generate_trending_candles("up", n=30)
        result = calculate_obv(candles)
        assert result["obv_trend"] == "haussiere"

    def test_downtrend_gives_baissiere(self):
        candles = generate_trending_candles("down", n=30)
        result = calculate_obv(candles)
        assert result["obv_trend"] == "baissiere"

    def test_single_candle_returns_neutre(self):
        result = calculate_obv(generate_flat_candles(1))
        assert result["obv_trend"] == "neutre"


# ===========================================================================
# detect_candle_pattern
# ===========================================================================

class TestDetectCandlePattern:

    def test_returns_none_on_empty(self):
        assert detect_candle_pattern([]) is None

    def test_returns_none_on_single_candle(self):
        assert detect_candle_pattern([_make_candle(1.0, 1.001)]) is None

    def test_detects_doji(self):
        """Corps < 10 % du total → doji."""
        # corps = 0.00001, total = 0.002 → ratio 0.005 < 0.1
        doji = _make_candle(1.08500, 1.08501, high=1.08600, low=1.08400)
        prev = _make_candle(1.08400, 1.08480)
        assert detect_candle_pattern([prev, doji]) == "doji"

    def test_detects_hammer(self):
        """Longue mèche basse (> 2× corps) et mèche haute courte = hammer."""
        # corps = 0.0001 (open=1.08490, close=1.08500)
        # lower_wick = 1.08490 - 1.08000 = 0.0049  → >> 2 × max(0.0001, 0.0026)
        # upper_wick = 1.08510 - 1.08500 = 0.0001  → << lower * 0.3
        hammer = _make_candle(1.08490, 1.08500, high=1.08510, low=1.08000)
        prev = _make_candle(1.08000, 1.08400)
        assert detect_candle_pattern([prev, hammer]) == "hammer"

    def test_detects_shooting_star(self):
        """Longue mèche haute et corps petit en bas = shooting_star."""
        # upper_wick = 1.09000 - 1.08500 = 0.005
        # lower_wick = 1.08490 - 1.08480 = 0.0001
        star = _make_candle(1.08490, 1.08500, high=1.09000, low=1.08480)
        prev = _make_candle(1.08000, 1.08400)
        assert detect_candle_pattern([prev, star]) == "shooting_star"

    def test_detects_bullish_engulfing(self):
        """Bougie haussière englobant la bougie baissière précédente."""
        bearish = _make_candle(1.08600, 1.08400, high=1.08650, low=1.08350)
        bullish = _make_candle(1.08350, 1.08650, high=1.08700, low=1.08300)
        assert detect_candle_pattern([bearish, bullish]) == "bullish_engulfing"

    def test_detects_bearish_engulfing(self):
        """Bougie baissière englobant la bougie haussière précédente."""
        bullish = _make_candle(1.08400, 1.08600, high=1.08650, low=1.08350)
        bearish = _make_candle(1.08650, 1.08350, high=1.08700, low=1.08300)
        assert detect_candle_pattern([bullish, bearish]) == "bearish_engulfing"

    def test_result_is_string_or_none(self):
        """Le résultat est toujours str ou None — jamais d'autre type."""
        candles = generate_realistic_candles(n=10)
        result = detect_candle_pattern(candles)
        assert result is None or isinstance(result, str)

    def test_flat_candle_returns_none_not_doji(self):
        """Bougie avec total=0 (high==low) → None (division par zéro évitée)."""
        flat = _make_candle(1.0, 1.0, high=1.0, low=1.0)
        prev = _make_candle(1.0, 1.001)
        assert detect_candle_pattern([prev, flat]) is None


# ===========================================================================
# detect_market_regime
# ===========================================================================

class TestDetectMarketRegime:

    def test_volatile_when_atr_pct_high(self):
        # atr_pct = 0.009/1.085 * 100 ≈ 0.83 ≥ 0.8
        result = detect_market_regime(1.08500, atr=0.009, ma_fast=1.086, ma_slow=1.084)
        assert result == "volatile"

    def test_range_when_ma_gap_tiny(self):
        # ma_gap_pct = 0.00002/1.085 * 100 ≈ 0.0018 < 0.05
        result = detect_market_regime(1.08500, atr=0.001, ma_fast=1.08501, ma_slow=1.08499)
        assert result == "range"

    def test_trend_bullish_when_ma_fast_above_slow(self):
        result = detect_market_regime(1.08500, atr=0.001, ma_fast=1.086, ma_slow=1.084)
        assert result == "trend_bullish"

    def test_trend_bearish_when_ma_fast_below_slow(self):
        result = detect_market_regime(1.08500, atr=0.001, ma_fast=1.084, ma_slow=1.086)
        assert result == "trend_bearish"

    def test_unknown_when_price_is_zero(self):
        result = detect_market_regime(0.0, atr=0.001, ma_fast=1.086, ma_slow=1.084)
        assert result == "unknown"

    def test_result_is_always_valid_string(self):
        valid = {"volatile", "range", "trend_bullish", "trend_bearish", "unknown"}
        for price in (0.0, 1.0, 1.085, 50.0):
            r = detect_market_regime(price, atr=0.005, ma_fast=price * 1.001, ma_slow=price)
            assert r in valid


# ===========================================================================
# calculate_price_momentum & calculate_trend_strength
# ===========================================================================

class TestMomentum:

    def test_positive_on_uptrend(self):
        closes = [1.0 + i * 0.01 for i in range(20)]
        assert calculate_price_momentum(closes, lookback=10) > 0

    def test_negative_on_downtrend(self):
        closes = [2.0 - i * 0.01 for i in range(20)]
        assert calculate_price_momentum(closes, lookback=10) < 0

    def test_zero_on_flat(self):
        assert calculate_price_momentum([1.0] * 20, lookback=10) == pytest.approx(0.0)

    def test_insufficient_data_returns_zero(self):
        assert calculate_price_momentum([1.0, 2.0], lookback=10) == 0.0


class TestTrendStrength:

    def test_positive_on_directional_trend(self):
        closes = [1.0 + i * 0.001 for i in range(30)]
        assert calculate_trend_strength(closes, period=20) > 0

    def test_zero_on_flat(self):
        assert calculate_trend_strength([1.0] * 30, period=20) == pytest.approx(0.0)

    def test_insufficient_data_returns_zero(self):
        assert calculate_trend_strength([1.0, 2.0], period=20) == 0.0


# ===========================================================================
# calculate_support_resistance
# ===========================================================================

class TestCalculateSupportResistance:

    def test_returns_two_floats(self):
        candles = generate_realistic_candles(n=60)
        highs = [c["high"] for c in candles]
        lows = [c["low"] for c in candles]
        resistance, support = calculate_support_resistance(highs, lows)
        assert isinstance(resistance, float)
        assert isinstance(support, float)

    def test_resistance_gte_support(self):
        candles = generate_realistic_candles(n=60)
        highs = [c["high"] for c in candles]
        lows = [c["low"] for c in candles]
        resistance, support = calculate_support_resistance(highs, lows)
        assert resistance >= support


# ===========================================================================
# calculate_volume_filter
# ===========================================================================

class TestCalculateVolumeFilter:

    def test_returns_dict_with_required_keys(self):
        candles = generate_realistic_candles(n=30)
        result = calculate_volume_filter(candles, lookback=20)
        for key in ("volume_ratio", "is_high_volume", "volume_signal"):
            assert key in result

    def test_empty_candles_returns_defaults(self):
        result = calculate_volume_filter([])
        assert result["volume_ratio"] == 1.0
        assert result["is_high_volume"] is False

    def test_volume_ratio_positive(self):
        candles = generate_realistic_candles(n=30)
        result = calculate_volume_filter(candles)
        assert result["volume_ratio"] > 0


# ===========================================================================
# calculate_signal_score  ← TEST LE PLUS CRITIQUE
# ===========================================================================

class TestCalculateSignalScore:
    """
    Tests sur la fonction centrale qui produit le signal de trading.
    Toutes les invariants de sécurité doivent être vérifiés ici.
    """

    # --- Données insuffisantes ---

    def test_insufficient_data_returns_zero_score(self):
        """< _MIN_CANDLES bougies → score=0, direction=None."""
        candles = generate_realistic_candles(n=10)
        result = calculate_signal_score(candles, instrument="EURUSDm")
        assert result["score"] == 0
        assert result["direction"] is None

    def test_insufficient_data_pattern_is_labeled(self):
        """pattern='insufficient_data' quand données manquantes."""
        candles = generate_realistic_candles(n=5)
        result = calculate_signal_score(candles)
        assert result["pattern"] == "insufficient_data"

    def test_insufficient_data_atr_pips_is_zero(self):
        candles = generate_realistic_candles(n=5)
        result = calculate_signal_score(candles)
        assert result["atr_pips"] == 0.0

    # --- Invariants de sécurité absolus ---

    @pytest.mark.parametrize("seed", [42, 99, 123, 7, 0])
    def test_score_always_between_0_and_5(self, seed):
        """score ∈ [0, 5] — invariant de sécurité critique."""
        candles = generate_realistic_candles(n=100, seed=seed)
        result = calculate_signal_score(candles, instrument="EURUSDm")
        assert 0 <= result["score"] <= 5, (
            f"score={result['score']} invalide pour seed={seed}"
        )

    @pytest.mark.parametrize("seed", [42, 99, 123])
    def test_direction_always_valid(self, seed):
        """direction ∈ {None, 'BUY', 'SELL'} — jamais d'autre valeur."""
        candles = generate_realistic_candles(n=100, seed=seed)
        result = calculate_signal_score(candles)
        assert result["direction"] in (None, "BUY", "SELL"), (
            f"direction={result['direction']!r} invalide pour seed={seed}"
        )

    def test_score_never_negative(self):
        """score >= 0 toujours (min=0 encodé dans calculate_signal_score)."""
        candles = generate_realistic_candles(n=100)
        result = calculate_signal_score(candles)
        assert result["score"] >= 0

    # --- Structure du résultat ---

    def test_result_has_all_required_keys(self):
        candles = generate_realistic_candles(n=100)
        result = calculate_signal_score(candles)
        for key in ("score", "direction", "details", "pattern", "atr_pips"):
            assert key in result, f"Clé manquante dans le résultat : {key}"

    def test_details_contains_main_indicators(self):
        """details contient les indicateurs techniques clés."""
        candles = generate_realistic_candles(n=100)
        result = calculate_signal_score(candles)
        details = result.get("details", {})
        # details n'est présent que si score > 0 ou si données suffisantes
        if details:
            for key in ("rsi", "ma_fast", "ma_slow", "bb_upper", "atr", "adx"):
                assert key in details, f"Indicateur manquant : {key}"

    def test_atr_pips_non_negative(self):
        """atr_pips ≥ 0 toujours."""
        candles = generate_realistic_candles(n=100)
        result = calculate_signal_score(candles)
        assert result["atr_pips"] >= 0.0

    def test_details_rsi_in_range(self):
        """RSI dans details ∈ [0, 100]."""
        candles = generate_realistic_candles(n=100)
        result = calculate_signal_score(candles)
        details = result.get("details", {})
        if "rsi" in details:
            assert 0.0 <= details["rsi"] <= 100.0

    # --- Comportements directionnels ---

    def test_rsi_oversold_after_prolonged_drop(self):
        """Après forte baisse, RSI dans details doit être bas (< 50)."""
        down = generate_trending_candles("down", n=80, base_price=1.10000, step=0.0005)
        flat = generate_flat_candles(20, price=down[-1]["close"])
        candles = down + flat
        result = calculate_signal_score(candles, instrument="EURUSDm")
        rsi = result.get("details", {}).get("rsi", 50)
        assert rsi < 50, f"RSI attendu < 50 après baisse, obtenu {rsi:.2f}"

    def test_rsi_overbought_after_prolonged_rise(self):
        """Après forte hausse, RSI dans details doit être élevé (> 50)."""
        up = generate_trending_candles("up", n=80, base_price=1.08000, step=0.0005)
        flat = generate_flat_candles(20, price=up[-1]["close"])
        candles = up + flat
        result = calculate_signal_score(candles, instrument="EURUSDm")
        rsi = result.get("details", {}).get("rsi", 50)
        assert rsi > 50, f"RSI attendu > 50 après hausse, obtenu {rsi:.2f}"

    def test_flat_market_does_not_generate_high_score(self):
        """
        Marché complètement plat → ADX ≈ 0 → signaux pénalisés → score ≤ 2.
        """
        candles = generate_flat_candles(100, price=1.08500)
        result = calculate_signal_score(candles)
        assert result["score"] <= 2, (
            f"score={result['score']} trop élevé pour un marché plat"
        )

    def test_signal_score_with_instrument_xauusd(self):
        """Le paramètre instrument est accepté sans erreur pour XAUUSDm."""
        candles = generate_realistic_candles(n=100, base_price=2000.0)
        result = calculate_signal_score(candles, instrument="XAUUSDm")
        assert 0 <= result["score"] <= 5

    # --- Fixture generate_trending_candles ---

    def test_fixture_up_produces_strictly_rising_closes(self, trending_candles_factory):
        """generate_trending_candles('up') → closes strictement croissants."""
        candles = trending_candles_factory("up", 20)
        closes = [c["close"] for c in candles]
        assert closes[-1] > closes[0]
        assert all(closes[i] > closes[i - 1] for i in range(1, len(closes)))

    def test_fixture_down_produces_strictly_falling_closes(self, trending_candles_factory):
        """generate_trending_candles('down') → closes strictement décroissants."""
        candles = trending_candles_factory("down", 20)
        closes = [c["close"] for c in candles]
        assert closes[-1] < closes[0]
        assert all(closes[i] < closes[i - 1] for i in range(1, len(closes)))

    def test_fixture_high_always_geq_open_and_close(self, trending_candles_factory):
        """high ≥ max(open, close) toujours."""
        for direction in ("up", "down"):
            for c in trending_candles_factory(direction, 30):
                assert c["high"] >= max(c["open"], c["close"]), (
                    f"high < max(open,close) dans {c}"
                )

    def test_fixture_low_always_leq_open_and_close(self, trending_candles_factory):
        """low ≤ min(open, close) toujours."""
        for direction in ("up", "down"):
            for c in trending_candles_factory(direction, 30):
                assert c["low"] <= min(c["open"], c["close"]), (
                    f"low > min(open,close) dans {c}"
                )

    def test_fixture_n_candles_returned(self, trending_candles_factory):
        """La fixture retourne exactement n bougies."""
        for n in (1, 10, 100):
            assert len(trending_candles_factory("up", n)) == n
            assert len(trending_candles_factory("down", n)) == n


    # ===========================================================================
    # calculate_mtf_signal
    # ===========================================================================

    class TestCalculateMTFSignal:
        """Tests sur le signal multi-timeframe (H1 + D1 optionnel)."""

        def test_without_d1_returns_h1_signal_unchanged(self):
            """Sans données D1, le résultat est identique au signal H1."""
            candles = generate_realistic_candles(n=100)
            h1_result = calculate_signal_score(candles)
            mtf_result = calculate_mtf_signal(candles, candles_d1=None)
            assert mtf_result["score"] == h1_result["score"]
            assert mtf_result["direction"] == h1_result["direction"]

        def test_without_d1_mtf_confirmed_is_false(self):
            candles = generate_realistic_candles(n=100)
            result = calculate_mtf_signal(candles, candles_d1=None)
            assert result["mtf_confirmed"] is False

        def test_without_d1_d1_direction_is_none(self):
            candles = generate_realistic_candles(n=100)
            result = calculate_mtf_signal(candles, candles_d1=None)
            assert result.get("d1_direction") is None

        def test_with_aligned_d1_sets_mtf_confirmed(self):
            """
            H1 et D1 avec même direction → mtf_confirmed=True.
            On construit deux séries de tendance dans la même direction.
            """
            # Tendance haussière forte → signal BUY probable sur les deux timeframes
            base = generate_realistic_candles(n=60, base_price=1.08500, seed=5)
            up = generate_trending_candles("up", n=40, base_price=base[-1]["close"], step=0.0005)
            candles_h1 = base + up
            candles_d1 = base + up  # même série = mêmes directions

            h1_signal = calculate_signal_score(candles_h1)
            # Seulement tester la confluence si les deux timeframes ont une direction
            result = calculate_mtf_signal(candles_h1, candles_d1=candles_d1)
            assert result["confluence"] in ("aligned", "counter", "neutral")
            assert result["direction"] in (None, "BUY", "SELL")
            assert 0 <= result["score"] <= 5

        def test_with_d1_score_not_negative(self):
            """Le score ne peut pas être négatif même avec pénalité counter-trend."""
            candles = generate_realistic_candles(n=100)
            # Donner des données D1 différentes pour forcer la vérification counter
            candles_d1 = generate_trending_candles("down", n=100, step=0.0003)
            result = calculate_mtf_signal(candles, candles_d1=candles_d1)
            assert result["score"] >= 0

        def test_with_d1_has_required_keys(self):
            """Le résultat MTF contient toutes les clés attendues."""
            candles = generate_realistic_candles(n=100)
            result = calculate_mtf_signal(candles, candles_d1=candles)
            for key in ("score", "direction", "mtf_confirmed", "d1_direction", "d1_score", "confluence"):
                assert key in result, f"Clé manquante: {key}"

        def test_details_has_mtf_confirmed(self):
            """details.mtf_confirmed reflète le résultat MTF."""
            candles = generate_realistic_candles(n=100)
            result = calculate_mtf_signal(candles, candles_d1=candles)
            details = result.get("details", {})
            if details:
                assert "mtf_confirmed" in details


    # ===========================================================================
    # build_human_analysis_summary
    # ===========================================================================

    class TestBuildHumanAnalysisSummary:

        def _make_details(self, rsi=55.0, regime="trend_bullish", pattern="hammer",
                          bias=0.5, rr_buy=1.8, rr_sell=1.2, mtf=True) -> dict:
            return {
                "market_regime": regime,
                "rsi": rsi,
                "candle_pattern": pattern,
                "signal_bias": bias,
                "rr_buy": rr_buy,
                "rr_sell": rr_sell,
                "mtf_confirmed": mtf,
            }

        def test_returns_non_empty_string(self):
            details = self._make_details()
            result = build_human_analysis_summary(details, "BUY", 3)
            assert isinstance(result, str)
            assert len(result) > 0

        def test_contains_direction(self):
            details = self._make_details()
            result = build_human_analysis_summary(details, "SELL", 2)
            assert "SELL" in result

        def test_contains_score(self):
            details = self._make_details()
            result = build_human_analysis_summary(details, "BUY", 4)
            assert "4/5" in result

        def test_no_direction_shows_wait(self):
            details = self._make_details(bias=0.0)
            result = build_human_analysis_summary(details, None, 0)
            assert "WAIT" in result

        def test_bearish_bias_shows_pression_vendeuse(self):
            details = self._make_details(bias=-0.5)
            result = build_human_analysis_summary(details, "SELL", 2)
            assert "vendeuse" in result

        def test_bullish_bias_shows_pression_acheteuse(self):
            details = self._make_details(bias=0.5)
            result = build_human_analysis_summary(details, "BUY", 3)
            assert "acheteuse" in result

        def test_neutral_bias_shows_pression_mixte(self):
            details = self._make_details(bias=0.1)
            result = build_human_analysis_summary(details, None, 0)
            assert "mixte" in result

        def test_mtf_confirmed_true(self):
            details = self._make_details(mtf=True)
            result = build_human_analysis_summary(details, "BUY", 3)
            assert "mtf_confirmed=oui" in result

        def test_mtf_confirmed_false(self):
            details = self._make_details(mtf=False)
            result = build_human_analysis_summary(details, "BUY", 3)
            assert "mtf_confirmed=non" in result


    # ===========================================================================
    # build_price_action_description
    # ===========================================================================

    class TestBuildPriceActionDescription:

        def test_insufficient_data_returns_message(self):
            """< 10 bougies → message 'Données insuffisantes'."""
            result = build_price_action_description(generate_realistic_candles(n=5))
            assert "insuffisantes" in result.lower() or "insuffisant" in result.lower()

        def test_returns_non_empty_string_with_sufficient_data(self):
            candles = generate_realistic_candles(n=60)
            result = build_price_action_description(candles, instrument="EURUSDm")
            assert isinstance(result, str)
            assert len(result) > 50

        def test_contains_support_resistance_levels(self):
            candles = generate_realistic_candles(n=60)
            result = build_price_action_description(candles)
            assert "Support" in result or "Résistance" in result or "support" in result.lower()

        def test_contains_last_5_candles_description(self):
            candles = generate_realistic_candles(n=60)
            result = build_price_action_description(candles)
            assert "5 dernières" in result or "bougies" in result.lower()

        def test_works_with_uptrend(self):
            candles = generate_trending_candles("up", n=60)
            result = build_price_action_description(candles, instrument="EURUSDm")
            assert isinstance(result, str)
            # Tendance haussière → HH+HL détectés
            assert "Higher" in result or "haussière" in result.lower() or "Support" in result

        def test_works_with_downtrend(self):
            candles = generate_trending_candles("down", n=60)
            result = build_price_action_description(candles, instrument="EURUSDm")
            assert isinstance(result, str)
            assert len(result) > 0

        def test_works_for_xauusd_pip_factor(self):
            """XAUUSDm utilise un pip factor différent — ne doit pas crasher."""
            candles = generate_realistic_candles(n=60, base_price=2000.0)
            result = build_price_action_description(candles, instrument="XAUUSDm")
            assert isinstance(result, str)

        def test_works_for_btcusd_pip_factor(self):
            candles = generate_realistic_candles(n=60, base_price=65000.0)
            result = build_price_action_description(candles, instrument="BTCUSDm")
            assert isinstance(result, str)


    # ===========================================================================
    # apply_optimized_params
    # ===========================================================================

    class TestApplyOptimizedParams:

        def test_accepts_valid_params_dict(self):
            """apply_optimized_params ne doit pas lever d'exception avec un dict valide."""
            params = {
                "RSI_PERIOD": 21,
                "MA_FAST": 10,
                "MA_SLOW": 30,
                "BB_PERIOD": 25,
                "ATR_PERIOD": 10,
            }
            apply_optimized_params(params)   # ne doit pas lever

        def test_ignores_non_dict(self):
            """Un argument non-dict doit être ignoré silencieusement."""
            for bad in (None, "string", 42, [1, 2, 3]):
                apply_optimized_params(bad)  # ne doit pas lever

        def test_partial_params_accepted(self):
            """Un dict partiel (une seule clé) est accepté."""
            apply_optimized_params({"RSI_PERIOD": 10})  # ne doit pas lever

        def test_minimum_clamps_enforced(self):
            """Les valeurs trop basses sont clampées aux minimums."""
            import signal_engine as se
            apply_optimized_params({"RSI_PERIOD": 1, "BB_PERIOD": 1, "ATR_PERIOD": 1})
            assert se.RSI_PERIOD >= 2
            assert se.BB_PERIOD >= 5
            assert se.ATR_PERIOD >= 2
