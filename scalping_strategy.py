"""
Système de Scalping Professionnel
==================================
Conçu pour M1/M5 avec :
- EMA rapides (9/21) pour détecter les micro-tendances
- Stochastique (5,3,3) pour les zones de surextension rapide
- Filtre de spread strict (pas d'entrée si spread trop large)
- Filtre de session (Kill Zones uniquement : London/NY open)
- Confirmation de volume
- SL/TP basés sur l'ATR (très serrés)
- Deux modes : MOMENTUM (breakout) et MEAN_REVERSION (bounce)

Usage:
    from scalping_strategy import calculate_scalp_signal
    result = calculate_scalp_signal(candles_m1, instrument="EURUSD", spread_pips=0.8)
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from settings import (
    SCALP_EMA_FAST, SCALP_EMA_SLOW, SCALP_STOCH_K, SCALP_STOCH_D, SCALP_STOCH_SMOOTH,
    SCALP_ATR_PERIOD, SCALP_SL_ATR_MULT, SCALP_TP_ATR_MULT,
    SCALP_MAX_SPREAD_FOREX, SCALP_MAX_SPREAD_GOLD, SCALP_MAX_SPREAD_CRYPTO,
    SCALP_MIN_VOLUME_RATIO, SCALP_MIN_SCORE, SCALP_ONLY_KILL_ZONES,
    SCALP_ADX_MIN_TREND, SCALP_MODE,
)

# ─────────────────────────────────────────────────────────────────────────────
# Kill Zones scalping (sous-ensemble plus strict que smart_strategies)
# ─────────────────────────────────────────────────────────────────────────────

# Fenêtres UTC où le scalping est autorisé
SCALP_KILL_ZONES = [
    (7, 10),   # London Open
    (12, 15),  # New York Open
    (13, 16),  # NY/London overlap
]


def _is_scalp_kill_zone() -> bool:
    """Retourne True si on est dans une Kill Zone autorisée pour le scalping."""
    hour = datetime.now(timezone.utc).hour
    for start, end in SCALP_KILL_ZONES:
        if start <= hour < end:
            return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Indicateurs rapides pour scalping
# ─────────────────────────────────────────────────────────────────────────────

def _ema(closes: List[float], period: int) -> float:
    """EMA standard."""
    if len(closes) < period:
        return closes[-1] if closes else 0.0
    k = 2.0 / (period + 1)
    ema = sum(closes[:period]) / period
    for price in closes[period:]:
        ema = price * k + ema * (1.0 - k)
    return ema


def _ema_series(closes: List[float], period: int) -> List[float]:
    """Série complète d'EMA pour calculer croisements."""
    if len(closes) < period:
        return [closes[-1]] * len(closes)
    k = 2.0 / (period + 1)
    result = []
    ema = sum(closes[:period]) / period
    for i in range(period):
        result.append(ema)
    for price in closes[period:]:
        ema = price * k + ema * (1.0 - k)
        result.append(ema)
    return result


def _stochastic(
    closes: List[float], highs: List[float], lows: List[float],
    k_period: int = 5, smooth_k: int = 3, d_period: int = 3
) -> Tuple[float, float]:
    """
    Stochastique rapide (Fast %K puis lissé en Slow %K et %D).
    Retourne (%K, %D). Valeur entre 0 et 100.
    Zones : < 20 = survente (signal achat), > 80 = surachat (signal vente).
    """
    needed = k_period + smooth_k + d_period - 2
    if len(closes) < needed:
        return 50.0, 50.0

    # Fast %K brut pour chaque bougie
    raw_k_series = []
    for i in range(k_period - 1, len(closes)):
        hh = max(highs[i - k_period + 1: i + 1])
        ll = min(lows[i - k_period + 1: i + 1])
        rng = hh - ll
        if rng == 0:
            raw_k_series.append(50.0)
        else:
            raw_k_series.append((closes[i] - ll) / rng * 100.0)

    # Slow %K = SMA(smooth_k) sur Fast %K
    if len(raw_k_series) < smooth_k:
        return 50.0, 50.0
    slow_k_series = []
    for i in range(smooth_k - 1, len(raw_k_series)):
        slow_k_series.append(sum(raw_k_series[i - smooth_k + 1: i + 1]) / smooth_k)

    # %D = SMA(d_period) sur Slow %K
    if len(slow_k_series) < d_period:
        return slow_k_series[-1], slow_k_series[-1]
    d_series = []
    for i in range(d_period - 1, len(slow_k_series)):
        d_series.append(sum(slow_k_series[i - d_period + 1: i + 1]) / d_period)

    return slow_k_series[-1], d_series[-1]


def _atr_scalp(candles: List[Dict], period: int) -> float:
    """ATR Wilder pour scalping."""
    if len(candles) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(candles)):
        h = candles[i]["high"]
        l = candles[i]["low"]
        pc = candles[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return atr


def _adx_scalp(candles: List[Dict], period: int = 14) -> float:
    """ADX simplifié pour scalping."""
    if len(candles) < period * 2 + 1:
        return 0.0
    plus_dms, minus_dms, trs = [], [], []
    for i in range(1, len(candles)):
        h, l = candles[i]["high"], candles[i]["low"]
        ph, pl = candles[i - 1]["high"], candles[i - 1]["low"]
        pc = candles[i - 1]["close"]
        plus_dm = max(h - ph, 0) if (h - ph) > (pl - l) else 0
        minus_dm = max(pl - l, 0) if (pl - l) > (h - ph) else 0
        tr = max(h - l, abs(h - pc), abs(l - pc))
        plus_dms.append(plus_dm)
        minus_dms.append(minus_dm)
        trs.append(tr)

    def _smooth(lst: List[float], p: int) -> List[float]:
        r = [sum(lst[:p])]
        for v in lst[p:]:
            r.append(r[-1] - r[-1] / p + v)
        return r

    atr_s = _smooth(trs, period)
    plus_s = _smooth(plus_dms, period)
    minus_s = _smooth(minus_dms, period)

    dx_list = []
    for a, p, m in zip(atr_s, plus_s, minus_s):
        if a == 0:
            continue
        pdi = 100 * p / a
        mdi = 100 * m / a
        dx_list.append(100 * abs(pdi - mdi) / (pdi + mdi) if (pdi + mdi) else 0)

    if not dx_list:
        return 0.0
    adx = sum(dx_list[:period]) / period
    for dx in dx_list[period:]:
        adx = (adx * (period - 1) + dx) / period
    return round(adx, 2)


def _volume_ratio(candles: List[Dict], lookback: int = 10) -> float:
    """Ratio volume dernière bougie vs moyenne des N dernières."""
    vols = [float(c.get("tick_volume", 0) or 0) for c in candles[-lookback:]]
    if not vols or sum(vols) == 0:
        return 1.0
    avg = sum(vols) / len(vols)
    last = float(candles[-1].get("tick_volume", 0) or 0)
    return round(last / avg, 2) if avg > 0 else 1.0


def _pip_factor(price: float, instrument: str) -> float:
    name = instrument.upper()
    if "BTC" in name or "ETH" in name:
        return 1.0
    if "XAU" in name or "XAG" in name:
        return 10.0
    if price >= 1000:
        return 10.0
    return 10000.0 if price < 20 else 100.0


def _max_spread(instrument: str) -> float:
    name = instrument.upper()
    if "XAU" in name or "XAG" in name:
        return SCALP_MAX_SPREAD_GOLD
    if "BTC" in name or "ETH" in name:
        return SCALP_MAX_SPREAD_CRYPTO
    return SCALP_MAX_SPREAD_FOREX


def _cfg_int(config: Optional[Dict[str, Any]], key: str, default: int) -> int:
    try:
        if config and key in config:
            return int(config[key])
    except Exception:
        pass
    return int(default)


def _cfg_float(config: Optional[Dict[str, Any]], key: str, default: float) -> float:
    try:
        if config and key in config:
            return float(config[key])
    except Exception:
        pass
    return float(default)


def _cfg_bool(config: Optional[Dict[str, Any]], key: str, default: bool) -> bool:
    if not config or key not in config:
        return bool(default)
    value = config[key]
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _cfg_str(config: Optional[Dict[str, Any]], key: str, default: str) -> str:
    if not config or key not in config:
        return str(default)
    return str(config[key]).strip()


def _max_spread_from_config(instrument: str, config: Optional[Dict[str, Any]]) -> float:
    name = instrument.upper()
    if "XAU" in name or "XAG" in name:
        return _cfg_float(config, "scalp_max_spread_gold", SCALP_MAX_SPREAD_GOLD)
    if "BTC" in name or "ETH" in name:
        return _cfg_float(config, "scalp_max_spread_crypto", SCALP_MAX_SPREAD_CRYPTO)
    return _cfg_float(config, "scalp_max_spread_forex", SCALP_MAX_SPREAD_FOREX)


# ─────────────────────────────────────────────────────────────────────────────
# Signal de scalping principal
# ─────────────────────────────────────────────────────────────────────────────

_MIN_CANDLES_SCALP = 60  # minimum pour tous les calculs scalping


def calculate_scalp_signal(
    candles: List[Dict],
    instrument: str = "",
    spread_pips: float = 0.0,
    config: Optional[Dict[str, Any]] = None,
) -> Dict:
    """
    Génère un signal de scalping avec score, direction, SL/TP et raisons.

    Paramètres
    ----------
    candles     : liste de bougies M1 ou M5 (dict avec open/high/low/close/tick_volume)
    instrument  : symbole MT5 (ex: "EURUSD", "XAUUSD")
    spread_pips : spread actuel en pips (pour filtrage)

    Retour
    ------
    {
        "signal":    "BUY" | "SELL" | "WAIT",
        "score":     int (0-6),
        "direction": "BUY" | "SELL" | None,
        "sl_pips":   float,
        "tp_pips":   float,
        "atr_pips":  float,
        "kill_zone": bool,
        "spread_ok": bool,
        "mode":      "momentum" | "mean_reversion",
        "reasons":   List[str],
        "details":   Dict,
    }
    """
    mode = _cfg_str(config, "scalp_mode", SCALP_MODE).lower()
    only_kill_zones = _cfg_bool(config, "scalp_only_kill_zones", SCALP_ONLY_KILL_ZONES)
    atr_period = _cfg_int(config, "scalp_atr_period", SCALP_ATR_PERIOD)
    ema_fast_period = _cfg_int(config, "scalp_ema_fast", SCALP_EMA_FAST)
    ema_slow_period = _cfg_int(config, "scalp_ema_slow", SCALP_EMA_SLOW)
    stoch_k_period = _cfg_int(config, "scalp_stoch_k", SCALP_STOCH_K)
    stoch_d_period = _cfg_int(config, "scalp_stoch_d", SCALP_STOCH_D)
    stoch_smooth_period = _cfg_int(config, "scalp_stoch_smooth", SCALP_STOCH_SMOOTH)
    min_volume_ratio = _cfg_float(config, "scalp_min_volume_ratio", SCALP_MIN_VOLUME_RATIO)
    min_score = _cfg_int(config, "scalp_min_score", SCALP_MIN_SCORE)
    adx_min_trend = _cfg_float(config, "scalp_adx_min_trend", SCALP_ADX_MIN_TREND)
    sl_atr_mult = _cfg_float(config, "scalp_sl_atr_mult", SCALP_SL_ATR_MULT)
    tp_atr_mult = _cfg_float(config, "scalp_tp_atr_mult", SCALP_TP_ATR_MULT)

    empty = {
        "signal": "WAIT", "score": 0, "direction": None,
        "sl_pips": 0.0, "tp_pips": 0.0, "atr_pips": 0.0,
        "kill_zone": False, "spread_ok": False, "mode": mode,
        "reasons": ["insufficient_data"], "details": {},
    }

    if len(candles) < _MIN_CANDLES_SCALP:
        return empty

    closes = [c["close"] for c in candles]
    highs  = [c["high"]  for c in candles]
    lows   = [c["low"]   for c in candles]
    current_price = closes[-1]

    # ── Filtre spread ────────────────────────────────────────────────────────
    max_spread = _max_spread_from_config(instrument, config)
    spread_ok = spread_pips <= max_spread

    # ── Filtre session ────────────────────────────────────────────────────────
    in_kill_zone = _is_scalp_kill_zone()
    if only_kill_zones and not in_kill_zone:
        return {**empty, "kill_zone": False, "spread_ok": spread_ok,
                "reasons": ["hors_kill_zone"]}

    if not spread_ok:
        return {**empty, "kill_zone": in_kill_zone, "spread_ok": False,
                "reasons": [f"spread_trop_large ({spread_pips:.1f}p > {max_spread}p)"]}

    # ── Indicateurs ──────────────────────────────────────────────────────────
    pip_f = _pip_factor(current_price, instrument)
    atr   = _atr_scalp(candles, atr_period)
    atr_pips = round(atr * pip_f, 1)
    adx   = _adx_scalp(candles, 14)
    vol_r = _volume_ratio(candles, lookback=10)

    ema_fast_series = _ema_series(closes, ema_fast_period)
    ema_slow_series = _ema_series(closes, ema_slow_period)
    ema_fast = ema_fast_series[-1]
    ema_slow = ema_slow_series[-1]
    prev_ema_fast = ema_fast_series[-2] if len(ema_fast_series) >= 2 else ema_fast
    prev_ema_slow = ema_slow_series[-2] if len(ema_slow_series) >= 2 else ema_slow

    stoch_k, stoch_d = _stochastic(
        closes, highs, lows,
        stoch_k_period, stoch_smooth_period, stoch_d_period
    )
    prev_stoch_k, prev_stoch_d = _stochastic(
        closes[:-1], highs[:-1], lows[:-1],
        stoch_k_period, stoch_smooth_period, stoch_d_period
    ) if len(closes) > _MIN_CANDLES_SCALP else (stoch_k, stoch_d)

    # Micro-structure prix (5 dernières bougies)
    micro_highs = highs[-5:]
    micro_lows  = lows[-5:]
    higher_highs = micro_highs[-1] > max(micro_highs[:-1])
    higher_lows  = micro_lows[-1]  > min(micro_lows[:-1])
    lower_highs  = micro_highs[-1] < max(micro_highs[:-1])
    lower_lows   = micro_lows[-1]  < min(micro_lows[:-1])

    details = {
        "ema_fast": round(ema_fast, 5),
        "ema_slow": round(ema_slow, 5),
        "ema_cross": "bullish" if ema_fast > ema_slow else "bearish",
        "stoch_k": round(stoch_k, 2),
        "stoch_d": round(stoch_d, 2),
        "atr": round(atr, 5),
        "atr_pips": atr_pips,
        "adx": round(adx, 2),
        "volume_ratio": vol_r,
        "kill_zone": in_kill_zone,
        "spread_pips": spread_pips,
        "higher_highs": higher_highs,
        "higher_lows": higher_lows,
        "lower_highs": lower_highs,
        "lower_lows": lower_lows,
        "price": round(current_price, 5),
    }

    # ── Scoring selon mode ────────────────────────────────────────────────────
    bullish = 0.0
    bearish = 0.0
    reasons_buy: List[str] = []
    reasons_sell: List[str] = []

    if mode == "momentum":
        # Mode MOMENTUM : on trade dans la direction de la tendance courte
        # Signal 1 – Croisement EMA (golden/death cross)
        golden_cross = ema_fast > ema_slow and prev_ema_fast <= prev_ema_slow
        death_cross  = ema_fast < ema_slow and prev_ema_fast >= prev_ema_slow

        if golden_cross:
            bullish += 2.0
            reasons_buy.append("EMA golden cross (momentum haussier)")
        elif death_cross:
            bearish += 2.0
            reasons_sell.append("EMA death cross (momentum baissier)")
        elif ema_fast > ema_slow:
            bullish += 1.0
            reasons_buy.append("EMA fast > slow")
        else:
            bearish += 1.0
            reasons_sell.append("EMA fast < slow")

        # Signal 2 – ADX tendance forte
        if adx >= adx_min_trend:
            if ema_fast > ema_slow:
                bullish += 1.0
                reasons_buy.append(f"ADX={adx:.1f} tendance forte")
            else:
                bearish += 1.0
                reasons_sell.append(f"ADX={adx:.1f} tendance forte")

        # Signal 3 – Stochastique (pas surachète/survendu contre tendance)
        if ema_fast > ema_slow and stoch_k < 80:
            bullish += 0.5
            reasons_buy.append(f"Stoch K={stoch_k:.1f} non surachète")
        elif ema_fast < ema_slow and stoch_k > 20:
            bearish += 0.5
            reasons_sell.append(f"Stoch K={stoch_k:.1f} non survendu")

        # Signal 4 – Structure micro-prix
        if higher_highs and higher_lows:
            bullish += 1.0
            reasons_buy.append("HH+HL structure haussière")
        elif lower_highs and lower_lows:
            bearish += 1.0
            reasons_sell.append("LH+LL structure baissière")

        # Signal 5 – Volume
        if vol_r >= min_volume_ratio:
            if ema_fast > ema_slow:
                bullish += 0.5
                reasons_buy.append(f"Volume ratio={vol_r:.2f} confirme")
            else:
                bearish += 0.5
                reasons_sell.append(f"Volume ratio={vol_r:.2f} confirme")

    elif mode == "mean_reversion":
        # Mode MEAN REVERSION : on trade les rebonds aux extrêmes
        # Signal 1 – Stochastique survente/surachat
        stoch_cross_up   = stoch_k > stoch_d and prev_stoch_k <= prev_stoch_d
        stoch_cross_down = stoch_k < stoch_d and prev_stoch_k >= prev_stoch_d

        if stoch_k < 20 and stoch_cross_up:
            bullish += 2.0
            reasons_buy.append(f"Stoch crossover K>{stoch_d:.1f} zone survente ({stoch_k:.1f})")
        elif stoch_k > 80 and stoch_cross_down:
            bearish += 2.0
            reasons_sell.append(f"Stoch crossover K<{stoch_d:.1f} zone surachat ({stoch_k:.1f})")
        elif stoch_k < 25:
            bullish += 1.0
            reasons_buy.append(f"Stoch zone survente ({stoch_k:.1f})")
        elif stoch_k > 75:
            bearish += 1.0
            reasons_sell.append(f"Stoch zone surachat ({stoch_k:.1f})")

        # Signal 2 – Prix proche EMA lente (zone de rebond)
        dist_to_slow_ema = abs(current_price - ema_slow)
        half_atr = atr * 0.5
        if dist_to_slow_ema <= half_atr:
            if current_price > ema_slow:
                bullish += 1.0
                reasons_buy.append("Prix au contact EMA slow (support dynamique)")
            else:
                bearish += 1.0
                reasons_sell.append("Prix au contact EMA slow (résistance dynamique)")

        # Signal 3 – Rejet chandelier
        last_c = candles[-1]
        body = abs(last_c["close"] - last_c["open"])
        total = last_c["high"] - last_c["low"]
        if total > 0:
            lower_wick = min(last_c["open"], last_c["close"]) - last_c["low"]
            upper_wick = last_c["high"] - max(last_c["open"], last_c["close"])
            if lower_wick > body * 2 and lower_wick > total * 0.4:
                bullish += 1.5
                reasons_buy.append("Pin bar / marteau (rejet haussier)")
            elif upper_wick > body * 2 and upper_wick > total * 0.4:
                bearish += 1.5
                reasons_sell.append("Shooting star (rejet baissier)")

        # Signal 4 – ADX faible (pas de tendance = range = bon pour MR)
        if adx < 25:
            if bullish > bearish:
                bullish += 0.5
                reasons_buy.append(f"ADX={adx:.1f} range favorable MR")
            elif bearish > bullish:
                bearish += 0.5
                reasons_sell.append(f"ADX={adx:.1f} range favorable MR")

        # Signal 5 – Volume
        if vol_r >= min_volume_ratio:
            if bullish > bearish:
                bullish += 0.5
                reasons_buy.append(f"Volume ratio={vol_r:.2f} confirme rebond")
            elif bearish > bullish:
                bearish += 0.5
                reasons_sell.append(f"Volume ratio={vol_r:.2f} confirme rebond")

    # ── Décision finale ───────────────────────────────────────────────────────
    if bullish >= bearish:
        raw_score = bullish
        direction = "BUY"
        reasons = reasons_buy
    else:
        raw_score = bearish
        direction = "SELL"
        reasons = reasons_sell

    score = min(int(raw_score), 6)

    # Kill zone bonus
    if in_kill_zone:
        score = min(score + 1, 6)
        reasons = reasons + ["kill_zone_active"]

    # ── SL / TP basés sur ATR ─────────────────────────────────────────────────
    sl_pips = round(max(atr_pips * sl_atr_mult, 3.0), 1)
    tp_pips = round(max(atr_pips * tp_atr_mult, sl_pips * 1.2), 1)

    # ── Décision finale ───────────────────────────────────────────────────────
    signal = direction if score >= min_score else "WAIT"

    return {
        "signal":    signal,
        "score":     score,
        "direction": direction if score >= min_score else None,
        "sl_pips":   sl_pips,
        "tp_pips":   tp_pips,
        "atr_pips":  atr_pips,
        "kill_zone": in_kill_zone,
        "spread_ok": spread_ok,
        "mode":      mode,
        "reasons":   reasons,
        "details":   details,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Filtre de cooldown (évite d'ouvrir plusieurs trades dans la même direction)
# ─────────────────────────────────────────────────────────────────────────────

class ScalpCooldownTracker:
    """
    Empêche d'ouvrir plusieurs trades scalping successifs sur la même paire
    trop rapidement. Stocké en mémoire (reset si le process redémarre).
    """

    def __init__(self, cooldown_bars: int = 3):
        """
        cooldown_bars : nombre de bougies à attendre après le dernier trade.
        Sur M1 : 3 bougies = 3 minutes.
        """
        self._last: Dict[str, int] = {}  # instrument → numéro de bougie
        self._cooldown = cooldown_bars
        self._bar_counter: Dict[str, int] = {}

    def tick(self, instrument: str) -> None:
        """Incrémenter le compteur de bougies pour cet instrument."""
        self._bar_counter[instrument] = self._bar_counter.get(instrument, 0) + 1

    def can_trade(self, instrument: str) -> bool:
        """True si le cooldown est écoulé."""
        last = self._last.get(instrument, -999)
        current = self._bar_counter.get(instrument, 0)
        return (current - last) >= self._cooldown

    def register_trade(self, instrument: str) -> None:
        """Appeler après l'ouverture d'un trade scalping."""
        self._last[instrument] = self._bar_counter.get(instrument, 0)


# Instance globale partagée
scalp_cooldown = ScalpCooldownTracker(cooldown_bars=3)


# ─────────────────────────────────────────────────────────────────────────────
# Résumé lisible
# ─────────────────────────────────────────────────────────────────────────────

def format_scalp_summary(result: Dict, instrument: str = "") -> str:
    """Formatte le résultat scalping en une ligne lisible pour les logs."""
    sig   = result.get("signal", "WAIT")
    score = result.get("score", 0)
    mode  = result.get("mode", "?")
    sl    = result.get("sl_pips", 0)
    tp    = result.get("tp_pips", 0)
    atr   = result.get("atr_pips", 0)
    kz    = "KZ✓" if result.get("kill_zone") else "kz✗"
    sp    = "sp✓" if result.get("spread_ok") else "sp✗"
    rsns  = " | ".join(result.get("reasons", []))
    sym   = f"[{instrument}] " if instrument else ""
    return (
        f"{sym}SCALP {sig} score={score}/6 mode={mode} "
        f"SL={sl}p TP={tp}p ATR={atr}p {kz} {sp} — {rsns}"
    )
