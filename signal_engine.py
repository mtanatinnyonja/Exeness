"""
Calcul des indicateurs techniques avancés.
RSI, MA, Bollinger Bands, ATR, momentum, régime marché et score de trading.
"""

import math
from typing import List, Dict, Tuple, Optional
from settings import (
    RSI_PERIOD, RSI_OVERSOLD, RSI_OVERBOUGHT,
    MA_FAST, MA_SLOW, BB_PERIOD, BB_STD, ATR_PERIOD
)


def calculate_rsi(closes: List[float], period: int = RSI_PERIOD) -> float:
    if len(closes) < period + 1:
        return 50.0
    deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    gains = [max(d, 0) for d in deltas[-period:]]
    losses = [abs(min(d, 0)) for d in deltas[-period:]]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calculate_ma(closes: List[float], period: int) -> float:
    if len(closes) < period:
        return closes[-1] if closes else 0
    return sum(closes[-period:]) / period


def calculate_ema(closes: List[float], period: int) -> float:
    if len(closes) < period:
        return closes[-1] if closes else 0
    k = 2 / (period + 1)
    ema = sum(closes[:period]) / period
    for price in closes[period:]:
        ema = price * k + ema * (1 - k)
    return ema


def calculate_bollinger(closes: List[float], period: int = BB_PERIOD, std_mult: float = BB_STD) -> Tuple[float, float, float]:
    """Retourne (upper, middle, lower)"""
    if len(closes) < period:
        c = closes[-1]
        return c, c, c
    recent = closes[-period:]
    ma = sum(recent) / period
    variance = sum((x - ma) ** 2 for x in recent) / period
    std = math.sqrt(variance)
    return ma + std_mult * std, ma, ma - std_mult * std


def calculate_atr(candles: List[Dict], period: int = ATR_PERIOD) -> float:
    if len(candles) < 2:
        return 0.0
    trs = []
    for i in range(1, len(candles)):
        high = candles[i]["high"]
        low = candles[i]["low"]
        prev_close = candles[i-1]["close"]
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
    return sum(trs[-period:]) / min(len(trs), period)


def calculate_macd(closes: List[float]) -> Tuple[float, float]:
    """Retourne (macd_line, signal_line)"""
    if len(closes) < 26:
        return 0.0, 0.0
    ema12 = calculate_ema(closes, 12)
    ema26 = calculate_ema(closes, 26)
    macd = ema12 - ema26
    # Signal simplifié
    recent_macds = []
    for i in range(9, 0, -1):
        sub = closes[:-i] if i > 0 else closes
        if len(sub) >= 26:
            e12 = calculate_ema(sub, 12)
            e26 = calculate_ema(sub, 26)
            recent_macds.append(e12 - e26)
    signal = sum(recent_macds[-9:]) / min(len(recent_macds), 9) if recent_macds else 0
    return macd, signal


def detect_candle_pattern(candles: List[Dict]) -> Optional[str]:
    """Détecte des patterns de chandeliers simples"""
    if len(candles) < 3:
        return None
    c = candles[-1]
    prev = candles[-2]
    body = abs(c["close"] - c["open"])
    total = c["high"] - c["low"]
    if total == 0:
        return None

    # Doji
    if body / total < 0.1:
        return "doji"

    # Marteau (bullish)
    lower_wick = min(c["open"], c["close"]) - c["low"]
    upper_wick = c["high"] - max(c["open"], c["close"])
    if lower_wick > 2 * body and upper_wick < body * 0.3:
        return "hammer"

    # Engulfing bullish
    if (c["close"] > c["open"] and prev["close"] < prev["open"] and
            c["close"] > prev["open"] and c["open"] < prev["close"]):
        return "bullish_engulfing"

    # Engulfing bearish
    if (c["close"] < c["open"] and prev["close"] > prev["open"] and
            c["close"] < prev["open"] and c["open"] > prev["close"]):
        return "bearish_engulfing"

    return None


def calculate_price_momentum(closes: List[float], lookback: int = 10) -> float:
    if len(closes) < lookback + 1:
        return 0.0
    base = closes[-lookback - 1]
    if base == 0:
        return 0.0
    return ((closes[-1] - base) / base) * 100


def calculate_trend_strength(closes: List[float], period: int = 20) -> float:
    if len(closes) < period + 1:
        return 0.0
    recent = closes[-period:]
    start = recent[0]
    if start == 0:
        return 0.0
    net_move = abs(recent[-1] - start)
    path = sum(abs(recent[i] - recent[i - 1]) for i in range(1, len(recent)))
    efficiency = (net_move / path) if path else 0.0
    slope_pct = abs((recent[-1] - start) / start) * 100
    return round(slope_pct * (0.5 + efficiency), 4)


def calculate_support_resistance(highs: List[float], lows: List[float], window: int = 20) -> Tuple[float, float]:
    if len(highs) < window or len(lows) < window:
        return max(highs[-5:] or [0]), min(lows[-5:] or [0])
    resistance = max(highs[-window:])
    support = min(lows[-window:])
    return resistance, support


def detect_market_regime(current_price: float, atr: float, ma_fast: float, ma_slow: float) -> str:
    if current_price <= 0:
        return "unknown"
    atr_pct = (atr / current_price) * 100
    ma_gap_pct = abs(ma_fast - ma_slow) / current_price * 100
    if atr_pct >= 0.8:
        return "volatile"
    if ma_gap_pct < 0.05:
        return "range"
    return "trend_bullish" if ma_fast >= ma_slow else "trend_bearish"


def calculate_signal_score(candles: List[Dict]) -> Dict:
    """
    Calcule un score de signal enrichi avec contexte de trading avancé.
    Retourne un dict avec score, direction, détails, ATR et qualité du trade.
    """
    if len(candles) < 60:
        return {"score": 0, "direction": None, "details": {}, "pattern": "insufficient_data", "atr_pips": 0.0}

    closes = [c["close"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]

    rsi = calculate_rsi(closes)
    ma_fast = calculate_ma(closes, MA_FAST)
    ma_slow = calculate_ma(closes, MA_SLOW)
    bb_upper, bb_mid, bb_lower = calculate_bollinger(closes)
    atr = calculate_atr(candles)
    macd, macd_signal = calculate_macd(closes)
    candle_pattern = detect_candle_pattern(candles)

    current_price = closes[-1]
    prev_ma_fast = calculate_ma(closes[:-1], MA_FAST)
    prev_ma_slow = calculate_ma(closes[:-1], MA_SLOW)
    momentum_5 = calculate_price_momentum(closes, 5)
    momentum_20 = calculate_price_momentum(closes, 20)
    trend_strength = calculate_trend_strength(closes, 20)
    resistance, support = calculate_support_resistance(highs[:-1], lows[:-1], 20)
    regime = detect_market_regime(current_price, atr, ma_fast, ma_slow)
    pip_factor = 100 if current_price >= 20 else 10000
    atr_pips = round(atr * pip_factor, 1)

    distance_to_resistance = max(0.0, (resistance - current_price) * pip_factor)
    distance_to_support = max(0.0, (current_price - support) * pip_factor)
    stop_hint = max(6.0, atr_pips)
    rr_buy = round(distance_to_resistance / stop_hint, 2) if stop_hint else 0.0
    rr_sell = round(distance_to_support / stop_hint, 2) if stop_hint else 0.0
    breakout_up = len(highs) > 21 and current_price > max(highs[-21:-1])
    breakout_down = len(lows) > 21 and current_price < min(lows[-21:-1])

    bullish_signals = 0.0
    bearish_signals = 0.0
    details = {
        "rsi": round(rsi, 2),
        "ma_fast": round(ma_fast, 5),
        "ma_slow": round(ma_slow, 5),
        "bb_upper": round(bb_upper, 5),
        "bb_middle": round(bb_mid, 5),
        "bb_lower": round(bb_lower, 5),
        "atr": round(atr, 5),
        "atr_pips": atr_pips,
        "macd": round(macd, 6),
        "macd_signal": round(macd_signal, 6),
        "candle_pattern": candle_pattern,
        "price": round(current_price, 5),
        "momentum_5": round(momentum_5, 4),
        "momentum_20": round(momentum_20, 4),
        "trend_strength": round(trend_strength, 4),
        "market_regime": regime,
        "support": round(support, 5),
        "resistance": round(resistance, 5),
        "distance_to_support_pips": round(distance_to_support, 1),
        "distance_to_resistance_pips": round(distance_to_resistance, 1),
        "rr_buy": rr_buy,
        "rr_sell": rr_sell,
        "breakout_up": breakout_up,
        "breakout_down": breakout_down,
    }

    if rsi < RSI_OVERSOLD:
        bullish_signals += 1
        details["rsi_signal"] = "oversold → bullish"
    elif rsi > RSI_OVERBOUGHT:
        bearish_signals += 1
        details["rsi_signal"] = "overbought → bearish"

    if ma_fast > ma_slow and prev_ma_fast <= prev_ma_slow:
        bullish_signals += 1.2
        details["ma_signal"] = "golden cross → bullish"
    elif ma_fast < ma_slow and prev_ma_fast >= prev_ma_slow:
        bearish_signals += 1.2
        details["ma_signal"] = "death cross → bearish"
    elif ma_fast > ma_slow:
        bullish_signals += 0.6
    else:
        bearish_signals += 0.6

    if current_price <= bb_lower:
        bullish_signals += 1
        details["bb_signal"] = "below lower band → bullish"
    elif current_price >= bb_upper:
        bearish_signals += 1
        details["bb_signal"] = "above upper band → bearish"

    if macd > macd_signal and macd > 0:
        bullish_signals += 1
        details["macd_signal_dir"] = "macd bullish"
    elif macd < macd_signal and macd < 0:
        bearish_signals += 1
        details["macd_signal_dir"] = "macd bearish"

    if momentum_5 > 0.08 and momentum_20 > 0:
        bullish_signals += 0.8
        details["momentum_signal"] = "momentum bullish"
    elif momentum_5 < -0.08 and momentum_20 < 0:
        bearish_signals += 0.8
        details["momentum_signal"] = "momentum bearish"

    if trend_strength >= 0.12:
        if regime == "trend_bullish":
            bullish_signals += 0.8
            details["trend_signal"] = "trend strength bullish"
        elif regime == "trend_bearish":
            bearish_signals += 0.8
            details["trend_signal"] = "trend strength bearish"

    if breakout_up:
        bullish_signals += 1
        details["breakout_signal"] = "breakout haussier"
    elif breakout_down:
        bearish_signals += 1
        details["breakout_signal"] = "breakout baissier"

    if candle_pattern in ["hammer", "bullish_engulfing"]:
        bullish_signals += 1
        details["pattern_signal"] = f"{candle_pattern} → bullish"
    elif candle_pattern in ["bearish_engulfing"]:
        bearish_signals += 1
        details["pattern_signal"] = f"{candle_pattern} → bearish"

    if bullish_signals > bearish_signals:
        score = min(5, int(round(bullish_signals)))
        direction = "BUY"
        pattern = details.get("breakout_signal", details.get("ma_signal", details.get("rsi_signal", "advanced_bullish")))
        rr = rr_buy
    elif bearish_signals > bullish_signals:
        score = min(5, int(round(bearish_signals)))
        direction = "SELL"
        pattern = details.get("breakout_signal", details.get("ma_signal", details.get("rsi_signal", "advanced_bearish")))
        rr = rr_sell
    else:
        score = 0
        direction = None
        pattern = "neutral"
        rr = max(rr_buy, rr_sell)

    details["signal_bias"] = round(bullish_signals - bearish_signals, 2)
    details["quality_score"] = round((score / 5) * min(1.5, max(rr, 0.5)), 2)

    return {
        "score": score,
        "direction": direction,
        "details": details,
        "pattern": pattern,
        "atr_pips": atr_pips,
    }
