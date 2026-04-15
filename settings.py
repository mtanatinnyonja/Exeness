"""
Configuration locale du robot MT5.
Aucun cloud, aucune API externe: seulement MT5, SQLite, apprentissage local
et option LLM local sur la machine.
"""

import os

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
LOCAL_LLM_TIMEOUT = int(os.getenv("LOCAL_LLM_TIMEOUT", "60"))
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

# === CAPITAL & RISK ===
INITIAL_CAPITAL = 50.0
MAX_RISK_PER_TRADE = 0.02
DAILY_TARGET = float(os.getenv("DAILY_TARGET", "2.0"))
DAILY_LOSS_LIMIT = float(os.getenv("DAILY_LOSS_LIMIT", "-5.0"))
MAX_OPEN_POSITIONS = int(os.getenv("MAX_OPEN_POSITIONS", "2"))
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
