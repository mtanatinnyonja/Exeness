"""
Calcul des indicateurs techniques avancés.
RSI (Wilder), MA, Bollinger Bands, ATR (Wilder), MACD (EMA propre),
momentum, régime marché, support/résistance par pivots et score de trading.
"""

import math
from typing import List, Dict, Tuple, Optional
from settings import (
    RSI_PERIOD, RSI_OVERSOLD, RSI_OVERBOUGHT,
    MA_FAST, MA_SLOW, BB_PERIOD, BB_STD, ATR_PERIOD
)


# ---------------------------------------------------------------------------
# Indicateurs de base
# ---------------------------------------------------------------------------

def calculate_rsi(closes: List[float], period: int = RSI_PERIOD) -> float:
    """
    RSI méthode Wilder (SMMA) — identique à MT5 / TradingView.
    Nécessite au moins period*2 + 1 valeurs pour un seed correct.
    """
    needed = period * 2 + 1
    if len(closes) < needed:
        return 50.0

    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]

    # Seed : SMA sur les `period` premiers deltas
    seed = deltas[:period]
    avg_gain = sum(max(d, 0) for d in seed) / period
    avg_loss = sum(abs(min(d, 0)) for d in seed) / period

    # Lissage Wilder (SMMA) sur le reste
    for d in deltas[period:]:
        gain = max(d, 0)
        loss = abs(min(d, 0))
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def calculate_ma(closes: List[float], period: int) -> float:
    if len(closes) < period:
        return closes[-1] if closes else 0.0
    return sum(closes[-period:]) / period


def calculate_ema(closes: List[float], period: int) -> float:
    """EMA standard (multiplicateur 2/(period+1))."""
    if len(closes) < period:
        return closes[-1] if closes else 0.0
    k = 2.0 / (period + 1)
    ema = sum(closes[:period]) / period
    for price in closes[period:]:
        ema = price * k + ema * (1.0 - k)
    return ema


def calculate_bollinger(
    closes: List[float], period: int = BB_PERIOD, std_mult: float = BB_STD
) -> Tuple[float, float, float]:
    """Retourne (upper, middle, lower)."""
    if len(closes) < period:
        c = closes[-1] if closes else 0.0
        return c, c, c
    recent = closes[-period:]
    ma = sum(recent) / period
    variance = sum((x - ma) ** 2 for x in recent) / period
    std = math.sqrt(variance)
    return ma + std_mult * std, ma, ma - std_mult * std


def calculate_atr(candles: List[Dict], period: int = ATR_PERIOD) -> float:
    """ATR lissé Wilder (SMMA) — identique à MT5."""
    if len(candles) < period + 1:
        return 0.0

    trs = []
    for i in range(1, len(candles)):
        high = candles[i]["high"]
        low = candles[i]["low"]
        prev_close = candles[i - 1]["close"]
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)

    # Seed SMA
    atr = sum(trs[:period]) / period
    # Lissage Wilder
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return atr


def calculate_macd(closes: List[float]) -> Tuple[float, float]:
    """
    MACD (12, 26, 9) avec signal EMA(9) correct sur la série MACD.
    Nécessite au moins 26 + 9 - 1 = 34 valeurs.
    """
    if len(closes) < 34:
        return 0.0, 0.0

    k12 = 2.0 / 13
    k26 = 2.0 / 27
    k9 = 2.0 / 10

    # Seed EMA12 et EMA26 sur les 26 premières bougies
    ema12 = sum(closes[:12]) / 12
    ema26 = sum(closes[:26]) / 26

    # Construction de la série MACD à partir de la bougie 26
    macd_series: List[float] = []
    for price in closes[12:26]:
        ema12 = price * k12 + ema12 * (1.0 - k12)
    for i, price in enumerate(closes[26:]):
        ema12 = price * k12 + ema12 * (1.0 - k12)
        ema26 = price * k26 + ema26 * (1.0 - k26)
        macd_series.append(ema12 - ema26)

    if len(macd_series) < 9:
        return macd_series[-1] if macd_series else 0.0, 0.0

    # Signal EMA(9) sur la série MACD
    signal = sum(macd_series[:9]) / 9
    for m in macd_series[9:]:
        signal = m * k9 + signal * (1.0 - k9)

    return macd_series[-1], signal


# ---------------------------------------------------------------------------
# Support / Résistance par pivots (plus robuste que max/min naïf)
# ---------------------------------------------------------------------------

def _find_pivot_highs(highs: List[float], lows: List[float], left: int = 3, right: int = 3) -> List[float]:
    """Retourne les niveaux pivot hauts sur la fenêtre donnée."""
    pivots = []
    n = len(highs)
    for i in range(left, n - right):
        if highs[i] == max(highs[i - left: i + right + 1]):
            pivots.append(highs[i])
    return pivots


def _find_pivot_lows(highs: List[float], lows: List[float], left: int = 3, right: int = 3) -> List[float]:
    """Retourne les niveaux pivot bas sur la fenêtre donnée."""
    pivots = []
    n = len(lows)
    for i in range(left, n - right):
        if lows[i] == min(lows[i - left: i + right + 1]):
            pivots.append(lows[i])
    return pivots


def calculate_support_resistance(
    highs: List[float], lows: List[float], window: int = 40
) -> Tuple[float, float]:
    """
    Support et résistance basés sur les niveaux pivot de la fenêtre.
    Fallback sur max/min si aucun pivot trouvé.
    """
    h = highs[-window:] if len(highs) >= window else highs
    l = lows[-window:] if len(lows) >= window else lows

    pivot_highs = _find_pivot_highs(h, l)
    pivot_lows = _find_pivot_lows(h, l)

    current_price = (highs[-1] + lows[-1]) / 2

    # Résistance = pivot haut le plus proche AU-DESSUS du prix actuel
    above = [p for p in pivot_highs if p > current_price]
    resistance = min(above) if above else max(h)

    # Support = pivot bas le plus proche EN-DESSOUS du prix actuel
    below = [p for p in pivot_lows if p < current_price]
    support = max(below) if below else min(l)

    return resistance, support


# ---------------------------------------------------------------------------
# Patterns chandelier
# ---------------------------------------------------------------------------

def detect_candle_pattern(candles: List[Dict]) -> Optional[str]:
    """Détecte les patterns de chandeliers : doji, hammer, shooting_star, engulfing."""
    if len(candles) < 2:
        return None
    c = candles[-1]
    prev = candles[-2]
    body = abs(c["close"] - c["open"])
    total = c["high"] - c["low"]
    if total == 0:
        return None

    upper_wick = c["high"] - max(c["open"], c["close"])
    lower_wick = min(c["open"], c["close"]) - c["low"]

    # Marteau (bullish) — longue mèche basse, petite mèche haute
    # Testé avant doji : un hammer avec petit body ne doit pas être classé doji
    if lower_wick > 2 * max(body, total * 0.05) and upper_wick < lower_wick * 0.3:
        return "hammer"

    # Shooting star (bearish) — longue mèche haute, petite mèche basse
    if upper_wick > 2 * max(body, total * 0.05) and lower_wick < upper_wick * 0.3:
        return "shooting_star"

    # Doji — corps très petit et mèches équilibrées
    if body / total < 0.1:
        return "doji"

    # Engulfing bullish
    if (
        c["close"] > c["open"]
        and prev["close"] < prev["open"]
        and c["close"] > prev["open"]
        and c["open"] < prev["close"]
    ):
        return "bullish_engulfing"

    # Engulfing bearish
    if (
        c["close"] < c["open"]
        and prev["close"] > prev["open"]
        and c["close"] < prev["open"]
        and c["open"] > prev["close"]
    ):
        return "bearish_engulfing"

    return None


# ---------------------------------------------------------------------------
# Momentum et tendance
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Régime marché
# ---------------------------------------------------------------------------

def detect_market_regime(
    current_price: float, atr: float, ma_fast: float, ma_slow: float
) -> str:
    if current_price <= 0:
        return "unknown"
    atr_pct = (atr / current_price) * 100
    ma_gap_pct = abs(ma_fast - ma_slow) / current_price * 100
    if atr_pct >= 0.8:
        return "volatile"
    if ma_gap_pct < 0.05:
        return "range"
    return "trend_bullish" if ma_fast >= ma_slow else "trend_bearish"


# ---------------------------------------------------------------------------
# Résumé lisible
# ---------------------------------------------------------------------------

def build_human_analysis_summary(
    details: Dict, direction: Optional[str], score: int
) -> str:
    regime = details.get("market_regime", "unknown")
    rsi = float(details.get("rsi", 50) or 50)
    pattern = details.get("candle_pattern") or "aucun pattern fort"
    bias = float(details.get("signal_bias", 0) or 0)
    rr_buy = float(details.get("rr_buy", 0) or 0)
    rr_sell = float(details.get("rr_sell", 0) or 0)
    rr = rr_buy if direction == "BUY" else rr_sell if direction == "SELL" else max(rr_buy, rr_sell)
    pressure = "acheteuse" if bias > 0.35 else "vendeuse" if bias < -0.35 else "mixte"
    action = direction or "WAIT"
    return (
        f"Lecture humaine: régime {regime}, pression {pressure}, "
        f"pattern {pattern}, RSI {rsi:.1f}, RR {rr:.2f}, score {score}/5, biais {action}."
    )


# ---------------------------------------------------------------------------
# Score principal
# ---------------------------------------------------------------------------

# Nombre minimum de bougies pour un calcul fiable
# RSI Wilder : period*2+1 = 29
# MACD : 34
# MA lente : 50
# S/R pivots : fenêtre 40 + marges
_MIN_CANDLES = max(RSI_PERIOD * 2 + 1, 34, MA_SLOW, 60)


def _pip_factor_for(current_price: float, instrument: str = "") -> float:
    """Return the pip factor consistent with mt5_bridge._pip_size."""
    name = str(instrument).upper()
    if name.startswith(("BTC", "ETH")):
        return 1.0        # BTC pip = 1.0 ($1)
    if name.startswith(("XAU", "XAG")):
        return 10.0       # XAU pip = 0.10
    if current_price >= 1000:
        return 10.0
    return 10000.0 if current_price < 20 else 100.0


def calculate_signal_score(candles: List[Dict], instrument: str = "") -> Dict:
    """
    Calcule un score de signal enrichi avec contexte de trading avancé.
    Retourne un dict avec score, direction, détails, ATR et qualité du trade.
    """
    if len(candles) < _MIN_CANDLES:
        return {
            "score": 0,
            "direction": None,
            "details": {},
            "pattern": "insufficient_data",
            "atr_pips": 0.0,
        }

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
    prev_closes = closes[:-1]
    prev_ma_fast = calculate_ma(prev_closes, MA_FAST)
    prev_ma_slow = calculate_ma(prev_closes, MA_SLOW)
    momentum_5 = calculate_price_momentum(closes, 5)
    momentum_20 = calculate_price_momentum(closes, 20)
    trend_strength = calculate_trend_strength(closes, 20)

    # S/R via pivots (fenêtre 40 bougies, hors la dernière)
    resistance, support = calculate_support_resistance(highs[:-1], lows[:-1], window=40)

    regime = detect_market_regime(current_price, atr, ma_fast, ma_slow)
    pip_factor = _pip_factor_for(current_price, instrument)
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
    details: Dict = {
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

    # --- RSI ---
    if rsi < RSI_OVERSOLD:
        bullish_signals += 1
        details["rsi_signal"] = "oversold → bullish"
    elif rsi > RSI_OVERBOUGHT:
        bearish_signals += 1
        details["rsi_signal"] = "overbought → bearish"

    # --- Croisements MA ---
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

    # --- Bollinger ---
    if current_price <= bb_lower:
        bullish_signals += 1
        details["bb_signal"] = "below lower band → bullish"
    elif current_price >= bb_upper:
        bearish_signals += 1
        details["bb_signal"] = "above upper band → bearish"

    # --- MACD ---
    if macd > macd_signal and macd > 0:
        bullish_signals += 1
        details["macd_signal_dir"] = "macd bullish"
    elif macd < macd_signal and macd < 0:
        bearish_signals += 1
        details["macd_signal_dir"] = "macd bearish"

    # --- Momentum ---
    if momentum_5 > 0.08 and momentum_20 > 0:
        bullish_signals += 0.8
        details["momentum_signal"] = "momentum bullish"
    elif momentum_5 < -0.08 and momentum_20 < 0:
        bearish_signals += 0.8
        details["momentum_signal"] = "momentum bearish"

    # --- Force de tendance ---
    if trend_strength >= 0.12:
        if regime == "trend_bullish":
            bullish_signals += 0.8
            details["trend_signal"] = "trend strength bullish"
        elif regime == "trend_bearish":
            bearish_signals += 0.8
            details["trend_signal"] = "trend strength bearish"

    # --- Breakout ---
    if breakout_up:
        bullish_signals += 1
        details["breakout_signal"] = "breakout haussier"
    elif breakout_down:
        bearish_signals += 1
        details["breakout_signal"] = "breakout baissier"

    # --- Patterns chandelier ---
    if candle_pattern == "doji":
        bullish_signals *= 0.85
        bearish_signals *= 0.85
        details["pattern_signal"] = "doji → hésitation / attente"
    elif candle_pattern in ("hammer", "bullish_engulfing"):
        bullish_signals += 1
        details["pattern_signal"] = f"{candle_pattern} → bullish"
    elif candle_pattern == "shooting_star":
        bearish_signals += 1
        details["pattern_signal"] = "shooting_star → bearish"
    elif candle_pattern == "bearish_engulfing":
        bearish_signals += 1
        details["pattern_signal"] = f"{candle_pattern} → bearish"

    # --- Résultat ---
    if bullish_signals > bearish_signals:
        score = min(5, int(round(bullish_signals)))
        direction: Optional[str] = "BUY"
        pattern = details.get(
            "breakout_signal",
            details.get("ma_signal", details.get("rsi_signal", "advanced_bullish")),
        )
        rr = rr_buy
    elif bearish_signals > bullish_signals:
        score = min(5, int(round(bearish_signals)))
        direction = "SELL"
        pattern = details.get(
            "breakout_signal",
            details.get("ma_signal", details.get("rsi_signal", "advanced_bearish")),
        )
        rr = rr_sell
    else:
        score = 0
        direction = None
        pattern = "neutral"
        rr = max(rr_buy, rr_sell)

    details["signal_bias"] = round(bullish_signals - bearish_signals, 2)
    details["quality_score"] = round((score / 5) * min(1.5, max(rr, 0.5)), 2)
    details["human_summary"] = build_human_analysis_summary(details, direction, score)

    return {
        "score": score,
        "direction": direction,
        "details": details,
        "pattern": pattern,
        "atr_pips": atr_pips,
    }