"""
Calcul des indicateurs techniques
RSI, MA, Bollinger Bands, ATR, Signal Score
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


def calculate_signal_score(candles: List[Dict]) -> Dict:
    """
    Calcule un score de signal sur 5
    Retourne un dict avec le score, la direction et les détails
    """
    if len(candles) < 60:
        return {"score": 0, "direction": None, "details": {}, "pattern": "insufficient_data"}

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

    # Détermine la direction
    bullish_signals = 0
    bearish_signals = 0
    details = {
        "rsi": round(rsi, 2),
        "ma_fast": round(ma_fast, 5),
        "ma_slow": round(ma_slow, 5),
        "bb_upper": round(bb_upper, 5),
        "bb_lower": round(bb_lower, 5),
        "atr": round(atr, 5),
        "macd": round(macd, 6),
        "macd_signal": round(macd_signal, 6),
        "candle_pattern": candle_pattern,
        "price": round(current_price, 5)
    }

    # RSI signal
    if rsi < RSI_OVERSOLD:
        bullish_signals += 1
        details["rsi_signal"] = "oversold → bullish"
    elif rsi > RSI_OVERBOUGHT:
        bearish_signals += 1
        details["rsi_signal"] = "overbought → bearish"

    # MA croisement
    if ma_fast > ma_slow and prev_ma_fast <= prev_ma_slow:
        bullish_signals += 1
        details["ma_signal"] = "golden cross → bullish"
    elif ma_fast < ma_slow and prev_ma_fast >= prev_ma_slow:
        bearish_signals += 1
        details["ma_signal"] = "death cross → bearish"
    elif ma_fast > ma_slow:
        bullish_signals += 0.5
    else:
        bearish_signals += 0.5

    # Bollinger Bands
    if current_price <= bb_lower:
        bullish_signals += 1
        details["bb_signal"] = "below lower band → bullish"
    elif current_price >= bb_upper:
        bearish_signals += 1
        details["bb_signal"] = "above upper band → bearish"

    # MACD
    if macd > macd_signal and macd > 0:
        bullish_signals += 1
        details["macd_signal_dir"] = "macd bullish"
    elif macd < macd_signal and macd < 0:
        bearish_signals += 1
        details["macd_signal_dir"] = "macd bearish"

    # Pattern de chandeliers
    if candle_pattern in ["hammer", "bullish_engulfing"]:
        bullish_signals += 1
        details["pattern_signal"] = f"{candle_pattern} → bullish"
    elif candle_pattern in ["bearish_engulfing"]:
        bearish_signals += 1
        details["pattern_signal"] = f"{candle_pattern} → bearish"

    # Score final
    if bullish_signals > bearish_signals:
        score = min(5, int(bullish_signals))
        direction = "BUY"
        pattern = details.get("ma_signal", details.get("rsi_signal", "mixed_bullish"))
    elif bearish_signals > bullish_signals:
        score = min(5, int(bearish_signals))
        direction = "SELL"
        pattern = details.get("ma_signal", details.get("rsi_signal", "mixed_bearish"))
    else:
        score = 0
        direction = None
        pattern = "neutral"

    return {
        "score": score,
        "direction": direction,
        "details": details,
        "pattern": pattern,
        "atr_pips": round(atr * 10000, 1) if "JPY" not in str(details) else round(atr * 100, 1)
    }
