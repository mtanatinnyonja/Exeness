"""
Configuration du Trading Agent Exness / MT5.
Première étape: détection directe d'un terminal MetaTrader 5 ouvert,
sans API Exness, avec mémoire locale et IA sobre en tokens.
"""

import os

# === BROKER ===
BROKER = "mt5"  # "mt5" | "demo" | "oanda"

# OANDA reste disponible en secours, mais non utilisé par défaut
OANDA_API_KEY = ""
OANDA_ACCOUNT_ID = ""
OANDA_ENV = "practice"  # "practice" | "live"

# === META TRADER 5 / EXNESS ===
MT5_TERMINAL_PATH = ""      # Exemple Windows: C:/Program Files/MetaTrader 5/terminal64.exe
MT5_LOGIN = None            # Laisse vide pour détecter le MT5 déjà ouvert
MT5_PASSWORD = ""
MT5_SERVER = ""
REQUIRE_DEMO_ACCOUNT = True
ALLOW_TRADE_EXECUTION = False   # Sécurité: analyse/paper-trade par défaut
MT5_MAGIC_NUMBER = 20260414
MT5_DEVIATION = 20

# Mode de sélection des paires:
# - preferred = seulement les paires choisies ici
# - visible = celles visibles dans MT5
# - hybrid = préférées + visibles
SYMBOL_SOURCE_MODE = os.getenv("SYMBOL_SOURCE_MODE", "preferred").strip().lower()
PREFERRED_SYMBOLS = [s.strip() for s in os.getenv("PREFERRED_SYMBOLS", "EURUSDm").split(",") if s.strip()]
MT5_USE_VISIBLE_SYMBOLS = SYMBOL_SOURCE_MODE in {"visible", "hybrid"}
MT5_MAX_VISIBLE_SYMBOLS = int(os.getenv("MAX_SYMBOLS_PER_CYCLE", "3"))
AUTONOMOUS_MODE = True
DASHBOARD_PORT = int(os.getenv("DASHBOARD_PORT", "8080"))

# === IA / TOKENS ===
AI_PROVIDER = os.getenv("AI_PROVIDER", "auto")  # auto = Gemini, puis Claude, puis logique locale
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-3-5-haiku-20241022")
MAX_API_CALLS_PER_DAY = 12
DAILY_TOKEN_BUDGET = 12000
CLAUDE_TEMPERATURE = 0.2

# === CAPITAL & RISK ===
INITIAL_CAPITAL = 50.0
MAX_RISK_PER_TRADE = 0.02
DAILY_TARGET = 2.0
DAILY_LOSS_LIMIT = -5.0
MAX_OPEN_POSITIONS = 2
POSITION_SIZE_USD = 1.0

# === INSTRUMENTS ===
INSTRUMENTS = [
    "EUR_USD",
    "GBP_USD",
]

# === TIMEFRAMES ===
PRIMARY_TIMEFRAME = "H1"
CONFIRM_TIMEFRAME = "M15"

# === SIGNAL FILTER ===
MIN_SIGNAL_SCORE = 3
SIGNAL_COOLDOWN_MINUTES = 30

# === INDICATEURS TECHNIQUES ===
RSI_PERIOD = 14
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70
MA_FAST = 20
MA_SLOW = 50
BB_PERIOD = 20
BB_STD = 2.0
ATR_PERIOD = 14

# === MÉMOIRE DE L'AGENT ===
MEMORY_FILE = "data/agent_memory.json"
TRADES_FILE = "data/trades_history.json"
RUNTIME_DB_FILE = "data/agent_runtime.db"
LOGS_DIR = "logs/"

# === SCHEDULER ===
CHECK_INTERVAL_MINUTES = 15
MARKET_OPEN_HOUR = 7
MARKET_CLOSE_HOUR = 20
TRADE_DAYS = [0, 1, 2, 3, 4]
