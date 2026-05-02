"""
Configuration locale du robot MT5.
Aucun cloud, aucune API externe: seulement MT5, SQLite, apprentissage local
et option LLM local sur la machine.
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

# === META TRADER 5 / EXNESS ===
MT5_TERMINAL_PATH = ""      # Exemple: C:/Program Files/MetaTrader 5/terminal64.exe
MT5_LOGIN = None            # Laisse vide pour détecter le MT5 déjà ouvert
MT5_PASSWORD = ""
MT5_SERVER = ""
REQUIRE_DEMO_ACCOUNT = True
ALLOW_TRADE_EXECUTION = False   # Sécurité: paper mode par défaut
MT5_MAGIC_NUMBER = 20260414
MT5_DEVIATION = 20

# === SÉLECTION DES SYMBOLES ===
# visible uniquement = seulement les symboles affichés dans MT5
SYMBOL_SOURCE_MODE = os.getenv("SYMBOL_SOURCE_MODE", "visible").strip().lower()
PREFERRED_SYMBOLS = [s.strip() for s in os.getenv("PREFERRED_SYMBOLS", "").split(",") if s.strip()]
MT5_MAX_VISIBLE_SYMBOLS = int(os.getenv("MAX_SYMBOLS_PER_CYCLE", "10"))
AUTONOMOUS_MODE = True
DASHBOARD_PORT = int(os.getenv("DASHBOARD_PORT", "8080"))

# === IA LOCALE ===
# ollama = LLM local via localhost, sans autre moteur
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
# Le système doit pouvoir fonctionner sans LLM.
LLM_ENABLED = os.getenv("LLM_ENABLED", "true").strip().lower() == "true"
LLM_AS_FINAL_VALIDATOR = os.getenv("LLM_AS_FINAL_VALIDATOR", "false").strip().lower() == "true"
# True  = utilise les signaux techniques purs si Ollama plante (score >= 4 requis)
# False = WAIT systématique — comportement original, plus conservateur
LLM_FALLBACK_TECHNICAL = os.getenv("LLM_FALLBACK_TECHNICAL", "true").strip().lower() == "true"

# === FILTRES DE SIGNAL ET CONTEXTE MARCHE ===
ENABLE_SIGNAL_QUALITY_FILTER = os.getenv("ENABLE_SIGNAL_QUALITY_FILTER", "true").strip().lower() == "true"
SIGNAL_QUALITY_MIN_SCORE = int(os.getenv("SIGNAL_QUALITY_MIN_SCORE", "2"))
SIGNAL_QUALITY_MIN_BIAS = float(os.getenv("SIGNAL_QUALITY_MIN_BIAS", "0.5"))
ENABLE_MARKET_CONTEXT = os.getenv("ENABLE_MARKET_CONTEXT", "true").strip().lower() == "true"
MAX_TRADES_PER_DAY = int(os.getenv("MAX_TRADES_PER_DAY", "4"))
TRADE_COOLDOWN_MINUTES = int(os.getenv("TRADE_COOLDOWN_MINUTES", "30"))

# === MODE TRADER HUMAIN ET PLANIFICATION ===
ENABLE_HUMAN_LIKE_MODE = os.getenv("ENABLE_HUMAN_LIKE_MODE", "false").strip().lower() == "true"
HUMAN_LIKE_MIN_SCORE = int(os.getenv("HUMAN_LIKE_MIN_SCORE", "3"))
HUMAN_LIKE_MIN_BIAS = float(os.getenv("HUMAN_LIKE_MIN_BIAS", "0.5"))
HUMAN_LIKE_MAX_RECENT_TRADES = int(os.getenv("HUMAN_LIKE_MAX_RECENT_TRADES", "2"))
HUMAN_LIKE_TARGET_TRADES_PER_DAY = int(os.getenv("HUMAN_LIKE_TARGET_TRADES_PER_DAY", "2"))
HUMAN_LIKE_MIN_TRADES_PER_DAY = int(os.getenv("HUMAN_LIKE_MIN_TRADES_PER_DAY", "1"))
ENABLE_AGENT_COMMUNICATION_MODE = os.getenv("ENABLE_AGENT_COMMUNICATION_MODE", "false").strip().lower() == "true"

# === CAPITAL & RISK ===
INITIAL_CAPITAL = 50.0
MAX_RISK_PER_TRADE = 0.02
DAILY_TARGET = float(os.getenv("DAILY_TARGET", "2.0"))
DAILY_LOSS_LIMIT = float(os.getenv("DAILY_LOSS_LIMIT", "-5.0"))
MAX_OPEN_POSITIONS = int(os.getenv("MAX_OPEN_POSITIONS", "3"))
POSITION_SIZE_USD = 1.0

# === INSTRUMENTS ===
# Vide = dynamique, prend tous les symboles visibles dans MT5 Market Watch
INSTRUMENTS = []

# === TIMEFRAMES ===
PRIMARY_TIMEFRAME = "M15"
CONFIRM_TIMEFRAME = "M5"

# === SIGNAL FILTER ===
MIN_SIGNAL_SCORE = 2
SIGNAL_COOLDOWN_MINUTES = 10

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
# smart = scan toutes les paires visibles, filtre par spread + qualité, prend les meilleures
SYMBOL_SELECTION_MODE = os.getenv("SYMBOL_SELECTION_MODE", "smart").strip().lower()
MAX_SPREAD_FILTER_FOREX = float(os.getenv("MAX_SPREAD_FILTER_FOREX", "2.5"))
MAX_SPREAD_FILTER_GOLD = float(os.getenv("MAX_SPREAD_FILTER_GOLD", "35.0"))
MAX_SPREAD_FILTER_CRYPTO = float(os.getenv("MAX_SPREAD_FILTER_CRYPTO", "80.0"))

# === MÉMOIRE & BASE LOCALE ===
MEMORY_FILE = "data/agent_memory.json"
TRADES_FILE = "data/trades_history.json"
RUNTIME_DB_FILE = "data/local_runtime.db"
LOGS_DIR = "logs/"

# === SCHEDULER ===
CHECK_INTERVAL_MINUTES = 5
MARKET_OPEN_HOUR = 1
MARKET_CLOSE_HOUR = 23
TRADE_DAYS = [0, 1, 2, 3, 4]