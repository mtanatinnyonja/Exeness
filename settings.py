"""
Configuration locale du robot MT5.
Aucun cloud, aucune API externe : seulement MT5, SQLite, apprentissage local
et LLM local (Ollama) — cerveau obligatoire de l'agent IA.
"""

import os
from pathlib import Path

# Charger .env si présent
_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    with open(_env_path, encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _key, _, _val = _line.partition("=")
                os.environ.setdefault(_key.strip(), _val.strip())

# === BROKER ===
BROKER = "mt5"  # "mt5" | "demo"
PAPER_TRADING = False

# === META TRADER 5 / EXNESS ===
MT5_TERMINAL_PATH = ""      # Exemple: C:/Program Files/MetaTrader 5/terminal64.exe
MT5_LOGIN = None            # Laisse vide pour détecter le MT5 déjà ouvert
MT5_PASSWORD = ""
MT5_SERVER = ""
REQUIRE_DEMO_ACCOUNT = True
ALLOW_TRADE_EXECUTION = False  # Garder False jusqu'à validation manuelle
MT5_MAGIC_NUMBER = 20260414
MT5_DEVIATION = 20

# === SÉLECTION DES SYMBOLES — XAUUSDm uniquement ===
SYMBOL_SOURCE_MODE = "fixed"
PREFERRED_SYMBOLS = ["XAUUSDm"]
MT5_MAX_VISIBLE_SYMBOLS = 1
DASHBOARD_PORT = int(os.getenv("DASHBOARD_PORT", "8080"))

# === IA LOCALE (Ollama — OBLIGATOIRE) ===
# Ollama est le cerveau de l'agent : sans lui, aucune position n'est ouverte.
AI_PROVIDER = os.getenv("AI_PROVIDER", "ollama").strip().lower()
LOCAL_LLM_MODEL = os.getenv("LOCAL_LLM_MODEL", "qwen2.5:3b").strip()
LOCAL_LLM_ENDPOINT = os.getenv("LOCAL_LLM_ENDPOINT", "http://127.0.0.1:11434/api/generate").strip()
LOCAL_LLM_TIMEOUT = int(os.getenv("LOCAL_LLM_TIMEOUT", "300"))
MAX_LLM_CALLS_PER_DAY = int(os.getenv("MAX_LLM_CALLS_PER_DAY", "0"))  # 0 = illimité
DAILY_TOKEN_BUDGET = int(os.getenv("DAILY_TOKEN_BUDGET", "0"))  # 0 = illimité
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.02"))
LLM_MIN_CONFIDENCE = float(os.getenv("LLM_MIN_CONFIDENCE", "0.60"))
LLM_ANALYSIS_MODE = os.getenv("LLM_ANALYSIS_MODE", "precision").strip().lower()
LLM_ANALYSIS_NOTES = os.getenv(
    "LLM_ANALYSIS_NOTES",
    "Analyse stricte, multi-confirmation, priorité à la précision et attente en cas de doute."
).strip()
LLM_MAX_CONTEXT_BARS = int(os.getenv("LLM_MAX_CONTEXT_BARS", "60"))
ONLY_ALLOW_LOCAL_LLM = True

# === LLM et IA ===
# Le LLM est OBLIGATOIRE : sans réponse Ollama, l'agent refuse de trader.
LLM_ENABLED = True
LLM_AS_FINAL_VALIDATOR = True
# Pas de fallback : si Ollama plante, on attend — pas de trade à la sauvette.
LLM_FALLBACK_TECHNICAL = False

# === FILTRES DE SIGNAL ET CONTEXTE MARCHE ===
ENABLE_SIGNAL_QUALITY_FILTER = os.getenv("ENABLE_SIGNAL_QUALITY_FILTER", "true").strip().lower() == "true"
SIGNAL_QUALITY_MIN_SCORE = 3
SIGNAL_QUALITY_MIN_BIAS = float(os.getenv("SIGNAL_QUALITY_MIN_BIAS", "0.5"))
ENABLE_MARKET_CONTEXT = os.getenv("ENABLE_MARKET_CONTEXT", "true").strip().lower() == "true"
MAX_TRADES_PER_DAY = 5
TRADE_COOLDOWN_MINUTES = 20

# === CAPITAL & RISK — Demo $100 XAU ===
INITIAL_CAPITAL = 100.0
MAX_RISK_PER_TRADE = 0.015  # 1.5% par trade
DAILY_TARGET = 5.0          # Objectif $5/jour
DAILY_LOSS_LIMIT = -10.0    # Stop si -$10 (10% du capital)
MAX_OPEN_POSITIONS = 1      # 1 seule position XAU à la fois
POSITION_SIZE_USD = 0.5

# === INSTRUMENTS — XAUUSDm uniquement ===
INSTRUMENTS = ["XAUUSDm"]

# === TIMEFRAMES — Optimaux XAU hybride ===
PRIMARY_TIMEFRAME = "H1"
CONFIRM_TIMEFRAME = "M15"

# === SIGNAL FILTER ===
MIN_SIGNAL_SCORE = 3
SIGNAL_COOLDOWN_MINUTES = 5

# === INDICATEURS TECHNIQUES ===
RSI_PERIOD = 14
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70
MA_FAST = 20
MA_SLOW = 50
BB_PERIOD = 20
BB_STD = 2.0
ATR_PERIOD = 14

# === TELEGRAM NOTIFICATIONS ===
TELEGRAM_ENABLED = True
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

# === SÉLECTION DYNAMIQUE DES PAIRES ===
SYMBOL_SELECTION_MODE = "fixed"
MAX_SPREAD_FILTER_FOREX = float(os.getenv("MAX_SPREAD_FILTER_FOREX", "2.5"))
MAX_SPREAD_FILTER_GOLD = 8.0   # Exness XAU spread normal ~3 pips
MAX_SPREAD_FILTER_CRYPTO = float(os.getenv("MAX_SPREAD_FILTER_CRYPTO", "80.0"))

# === MÉMOIRE & BASE LOCALE ===
MEMORY_FILE = "data/agent_memory.json"
TRADES_FILE = "data/trades_history.json"
RUNTIME_DB_FILE = "data/local_runtime.db"
LOGS_DIR = "logs/"

# === SCHEDULER — Sessions XAU (UTC) ===
CHECK_INTERVAL_MINUTES = 5
MARKET_OPEN_HOUR = 7    # London open
MARKET_CLOSE_HOUR = 21  # NY close
TRADE_DAYS = [0, 1, 2, 3, 4]  # Lundi-Vendredi

# Mode de moteur de signaux : classic | scalping | hybrid
STRATEGY_MODE = os.getenv("STRATEGY_MODE", "hybrid").strip().lower()

# Confirmation humaine obligatoire avant tout ordre réel (sécurité)
REQUIRE_HUMAN_CONFIRMATION = os.getenv("REQUIRE_HUMAN_CONFIRMATION", "false").strip().lower() in ("1", "true", "yes", "on")

# ═══════════════════════════════════════════════════════════════════════════
# SCALPING — paramètres du module scalping_strategy.py
# Timeframe cible : M1 ou M5
# ═══════════════════════════════════════════════════════════════════════════

# Mode de scalping : "momentum" (breakout) ou "mean_reversion" (rebonds)
SCALP_MODE = os.getenv("SCALP_MODE", "momentum").strip().lower()

# EMAs rapides pour détecter la micro-tendance
SCALP_EMA_FAST = int(os.getenv("SCALP_EMA_FAST", "9"))
SCALP_EMA_SLOW = int(os.getenv("SCALP_EMA_SLOW", "21"))

# Stochastique (K, D, lissage K)
SCALP_STOCH_K      = int(os.getenv("SCALP_STOCH_K", "5"))
SCALP_STOCH_D      = int(os.getenv("SCALP_STOCH_D", "3"))
SCALP_STOCH_SMOOTH = int(os.getenv("SCALP_STOCH_SMOOTH", "3"))

# ATR pour le calcul SL/TP
SCALP_ATR_PERIOD    = int(os.getenv("SCALP_ATR_PERIOD", "7"))
SCALP_SL_ATR_MULT   = 1.5   # SL large pour absorber la volatilité XAU
SCALP_TP_ATR_MULT   = 3.0   # TP ambitieux (XAU fait 50-200 pips par move)

# Filtre spread — valeurs en pips
SCALP_MAX_SPREAD_FOREX  = float(os.getenv("SCALP_MAX_SPREAD_FOREX",  "1.5"))
SCALP_MAX_SPREAD_GOLD   = 6.0   # Spread max XAU scalping
SCALP_MAX_SPREAD_CRYPTO = float(os.getenv("SCALP_MAX_SPREAD_CRYPTO", "60.0"))

# Filtre volume (ratio vs moyenne 10 bougies)
SCALP_MIN_VOLUME_RATIO = float(os.getenv("SCALP_MIN_VOLUME_RATIO", "1.1"))

# Score minimum pour valider un signal scalping (0-6)
SCALP_MIN_SCORE = 5  # Score 5+ requis pour éviter les scalps XAU faibles

# ADX minimum en mode MOMENTUM — tendance forte requise pour XAU
SCALP_ADX_MIN_TREND = 30.0

# Forcer les Kill Zones uniquement (London + NY)
SCALP_ONLY_KILL_ZONES = True

# Nombre max de trades scalping par heure (par instrument)
SCALP_MAX_TRADES_PER_HOUR = 2

# Timeframe MT5 pour le scalping ("M1" ou "M5")
SCALP_TIMEFRAME = os.getenv("SCALP_TIMEFRAME", "M5").strip().upper()