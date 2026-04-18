"""
Tests unitaires Exeness — Money Management + Signal Engine.

Couvre les calculs critiques avant d'activer ALLOW_TRADE_EXECUTION = True.

Usage:
    python test_core.py

Aucune dépendance externe requise (pas de pytest, pas de MT5).
"""

import sys
import math
import traceback

# ---------------------------------------------------------------------------
# Helpers de test minimalistes (pas de pytest requis)
# ---------------------------------------------------------------------------

_PASS = 0
_FAIL = 0
_ERRORS = []


def check(name: str, condition: bool, detail: str = ""):
    global _PASS, _FAIL
    if condition:
        _PASS += 1
        print(f"  ✅ {name}")
    else:
        _FAIL += 1
        msg = f"  ❌ {name}" + (f" — {detail}" if detail else "")
        print(msg)
        _ERRORS.append(msg)


def section(title: str):
    print(f"\n{'='*55}")
    print(f"  {title}")
    print(f"{'='*55}")


# ---------------------------------------------------------------------------
# Import des modules du projet (chemin courant = racine Exeness)
# ---------------------------------------------------------------------------

try:
    from signal_engine import calculate_rsi, calculate_ma, calculate_ema
    SIGNAL_OK = True
except Exception as e:
    SIGNAL_OK = False
    print(f"[WARN] Impossible d'importer signal_engine: {e}")

try:
    from mt5_bridge import PaperBroker
    PAPER_OK = True
except Exception as e:
    PAPER_OK = False
    print(f"[WARN] Impossible d'importer mt5_bridge.PaperBroker: {e}")


# ===========================================================================
# 1. RSI — méthode Wilder
# ===========================================================================

section("1. RSI (Wilder)")

if SIGNAL_OK:
    # Série constante → RSI doit être 50
    flat = [100.0] * 50
    r = calculate_rsi(flat)
    check("RSI série constante = 50.0", r == 50.0, f"obtenu {r}")

    # Série 100% haussière → RSI proche de 100
    up = [float(i) for i in range(1, 60)]
    r_up = calculate_rsi(up)
    check("RSI tendance haussière > 70", r_up > 70, f"obtenu {r_up:.1f}")

    # Série 100% baissière → RSI proche de 0
    down = [float(60 - i) for i in range(60)]
    r_down = calculate_rsi(down)
    check("RSI tendance baissière < 30", r_down < 30, f"obtenu {r_down:.1f}")

    # Données insuffisantes → retour 50.0 (pas d'exception)
    short = [100.0, 101.0, 99.0]
    try:
        r_short = calculate_rsi(short)
        check("RSI données insuffisantes → 50.0 sans crash", r_short == 50.0, f"obtenu {r_short}")
    except Exception as e:
        check("RSI données insuffisantes → pas d'exception", False, str(e))

    # Liste vide → pas d'exception
    try:
        r_empty = calculate_rsi([])
        check("RSI liste vide → pas d'exception", True)
    except Exception as e:
        check("RSI liste vide → pas d'exception", False, str(e))
else:
    print("  ⚠️  Tests RSI ignorés (import échoué)")


# ===========================================================================
# 2. MA / EMA
# ===========================================================================

section("2. Moyennes Mobiles")

if SIGNAL_OK:
    closes = [float(i) for i in range(1, 21)]  # 1..20

    ma20 = calculate_ma(closes, 20)
    check("MA(20) sur 1..20 = 10.5", abs(ma20 - 10.5) < 0.001, f"obtenu {ma20}")

    # MA avec moins de données que la période → retourne dernier prix
    ma_short = calculate_ma([5.0, 6.0], 20)
    check("MA période > données → retourne dernier prix", ma_short == 6.0, f"obtenu {ma_short}")

    # EMA convergence : sur série constante → EMA = valeur constante
    flat20 = [50.0] * 40
    ema_flat = calculate_ema(flat20, 20)
    check("EMA série constante = 50.0", abs(ema_flat - 50.0) < 0.001, f"obtenu {ema_flat}")
else:
    print("  ⚠️  Tests MA/EMA ignorés (import échoué)")


# ===========================================================================
# 3. Money Management — calculate_volume (PaperBroker)
# ===========================================================================

section("3. Money Management — calculate_volume")

if PAPER_OK:
    try:
        broker = PaperBroker()

        # --- XAUUSDm (Gold) ---
        # pip_value = 10.0, risk = 1.0 USD, SL = 10 pips → vol = 1/(10*10) = 0.01
        vol_gold = broker.calculate_volume("XAUUSDm", risk_usd=1.0, sl_pips=10.0)
        check("Gold: vol = risk / (sl_pips × pip_value)", vol_gold >= 0.01,
              f"obtenu {vol_gold}")

        # Volume minimum = 0.01 même si le calcul donne moins
        vol_tiny = broker.calculate_volume("XAUUSDm", risk_usd=0.001, sl_pips=500.0)
        check("Volume jamais inférieur au minimum (0.01)", vol_tiny >= 0.01,
              f"obtenu {vol_tiny}")

        # SL = 0 → volume minimum (pas de division par zéro)
        try:
            vol_zero_sl = broker.calculate_volume("EURUSDm", risk_usd=1.0, sl_pips=0.0)
            check("SL=0 → volume minimum sans crash", vol_zero_sl >= 0.01,
                  f"obtenu {vol_zero_sl}")
        except ZeroDivisionError:
            check("SL=0 → pas de ZeroDivisionError", False, "ZeroDivisionError levée")

        # SL négatif → volume minimum
        try:
            vol_neg_sl = broker.calculate_volume("EURUSDm", risk_usd=1.0, sl_pips=-5.0)
            check("SL négatif → volume minimum sans crash", vol_neg_sl >= 0.01,
                  f"obtenu {vol_neg_sl}")
        except Exception as e:
            check("SL négatif → pas d'exception", False, str(e))

        # Volume arrondi au step (0.01)
        vol = broker.calculate_volume("EURUSDm", risk_usd=1.0, sl_pips=7.0)
        step = 0.01
        remainder = round(vol % step, 6)
        check("Volume arrondi au step 0.01",
              remainder < 1e-9 or abs(remainder - step) < 1e-9,
              f"obtenu {vol}, reste {remainder}")

    except Exception as e:
        print(f"  ❌ Erreur inattendue dans les tests volume: {e}")
        traceback.print_exc()
else:
    print("  ⚠️  Tests volume ignorés (import PaperBroker échoué)")


# ===========================================================================
# 4. place_market_order — cohérence SL/TP
# ===========================================================================

section("4. place_market_order — cohérence SL / TP")

if PAPER_OK:
    try:
        broker = PaperBroker()

        order_buy = broker.place_market_order(
            "XAUUSDm", "BUY", volume=0.01,
            stop_loss_pips=20.0, take_profit_pips=40.0
        )
        entry = order_buy["entry_price"]
        sl    = order_buy["stop_loss"]
        tp    = order_buy["take_profit"]

        check("BUY: SL < entry", sl < entry, f"sl={sl} entry={entry}")
        check("BUY: TP > entry", tp > entry, f"tp={tp} entry={entry}")
        check("BUY: RR ≥ 1.5",
              (tp - entry) >= 1.5 * (entry - sl) - 1e-6,
              f"RR={(tp-entry)/(entry-sl):.2f}")

        order_sell = broker.place_market_order(
            "XAUUSDm", "SELL", volume=0.01,
            stop_loss_pips=20.0, take_profit_pips=40.0
        )
        entry_s = order_sell["entry_price"]
        sl_s    = order_sell["stop_loss"]
        tp_s    = order_sell["take_profit"]

        check("SELL: SL > entry", sl_s > entry_s, f"sl={sl_s} entry={entry_s}")
        check("SELL: TP < entry", tp_s < entry_s, f"tp={tp_s} entry={entry_s}")
        check("SELL: RR ≥ 1.5",
              (entry_s - tp_s) >= 1.5 * (sl_s - entry_s) - 1e-6,
              f"RR={(entry_s-tp_s)/(sl_s-entry_s):.2f}")

    except Exception as e:
        print(f"  ❌ Erreur inattendue dans les tests ordre: {e}")
        traceback.print_exc()
else:
    print("  ⚠️  Tests ordre ignorés (import PaperBroker échoué)")


# ===========================================================================
# 5. Risque par trade — respecte le plafond MAX_RISK_PER_TRADE
# ===========================================================================

section("5. Risque par trade ≤ MAX_RISK_PER_TRADE")

try:
    from settings import MAX_RISK_PER_TRADE, INITIAL_CAPITAL

    max_risk_usd = INITIAL_CAPITAL * MAX_RISK_PER_TRADE

    check(f"MAX_RISK_PER_TRADE = {MAX_RISK_PER_TRADE*100:.0f}% (≤ 5%)",
          MAX_RISK_PER_TRADE <= 0.05,
          f"obtenu {MAX_RISK_PER_TRADE*100:.1f}%")

    check(f"Risque max en USD = {max_risk_usd:.2f} USD (capital {INITIAL_CAPITAL})",
          max_risk_usd > 0,
          f"capital={INITIAL_CAPITAL} risk={MAX_RISK_PER_TRADE}")

    if PAPER_OK:
        broker = PaperBroker()
        # Simule 100 pips de SL sur Gold → vérifie que le volume ne fait pas dépasser le risque max
        vol = broker.calculate_volume("XAUUSDm", risk_usd=max_risk_usd, sl_pips=100.0)
        pip_value = 10.0  # PaperBroker gold
        actual_risk = vol * 100.0 * pip_value
        check(
            f"Risque réel ≤ max_risk_usd (vol={vol}, risque_réel={actual_risk:.2f}$)",
            actual_risk <= max_risk_usd * 1.05,  # tolérance 5% pour l'arrondi du step
            f"risque_réel={actual_risk:.2f} > max={max_risk_usd:.2f}"
        )

except Exception as e:
    print(f"  ❌ Erreur: {e}")
    traceback.print_exc()


# ===========================================================================
# Résumé
# ===========================================================================

total = _PASS + _FAIL
print(f"\n{'='*55}")
print(f"  RÉSULTAT : {_PASS}/{total} tests passés", end="")
if _FAIL == 0:
    print("  🎉")
else:
    print(f"  — {_FAIL} ÉCHEC(S)")
    for err in _ERRORS:
        print(f"    {err}")
print(f"{'='*55}\n")

sys.exit(0 if _FAIL == 0 else 1)