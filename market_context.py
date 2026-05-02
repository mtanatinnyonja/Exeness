"""
Analyse du contexte marché pour adapter les décisions de trading.
"""

from typing import Dict, List

from signal_engine import (
    calculate_atr, calculate_ma, calculate_price_momentum,
    calculate_trend_strength, detect_market_regime,
)
from settings import MA_FAST, MA_SLOW


def analyze_market_context(candles: List[Dict], instrument: str = "") -> Dict:
    closes = [c["close"] for c in candles]
    if len(closes) < max(MA_SLOW, 20):
        return {
            "category": "unknown",
            "reason": "données insuffisantes",
            "trend_strength": 0.0,
            "momentum": 0.0,
            "regime": "unknown",
        }

    current_price = closes[-1]
    atr = calculate_atr(candles)
    ma_fast = calculate_ma(closes, MA_FAST)
    ma_slow = calculate_ma(closes, MA_SLOW)
    regime = detect_market_regime(current_price, atr, ma_fast, ma_slow)
    trend_strength = calculate_trend_strength(closes, 20)
    momentum = calculate_price_momentum(closes, 10)
    atr_pct = (atr / current_price) * 100 if current_price else 0.0

    if regime == "range" and atr_pct < 0.75:
        category = "range"
        reason = "ma rapprochées + volatilité contenue"
    elif regime.startswith("trend") and trend_strength >= 0.08:
        category = "trend"
        reason = "tendance technique confirmée"
    else:
        category = "uncertain"
        reason = "marché indécis ou transition"

    return {
        "category": category,
        "reason": reason,
        "trend_strength": round(trend_strength, 4),
        "momentum": round(momentum, 4),
        "regime": regime,
        "atr_pct": round(atr_pct, 4),
    }
