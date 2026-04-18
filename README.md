# Agent IA Trading MT5

Agent de trading autonome MT5 en mode 100% local.

## Architecture

- **MT5 Broker** : Exness-MT5Trial9 (démo), connexion directe via MetaTrader5 Python
- **Agent IA** : Chain-of-Thought via Ollama (qwen2.5:3b) en localhost — aucun appel cloud
- **Mémoire persistante** : `data/agent_memory.json` + `data/trades_history.json` + SQLite (`data/local_runtime.db`)
- **Dashboard web** : cockpit temps réel sur http://localhost:8765

## Fichiers

| Fichier | Rôle |
|---------|------|
| `settings.py` | Configuration (paires, risque, seuils) |
| `run_bot.py` | Point d'entrée cycles de trading |
| `main.py` | Alias compatible (redirige vers run_bot) |
| `agent_core.py` | Cerveau de l'agent : Chain-of-Thought, appel LLM, décision |
| `trade_orchestrator.py` | Orchestration : cycles, exécution, gestion positions |
| `mt5_bridge.py` | Connexion MT5 + paper broker + money management |
| `signal_engine.py` | Indicateurs techniques et scoring (RSI, ATR, RR, régime) |
| `smart_strategies.py` | HTF bias, SMC, confluence, corrélation |
| `market_protection.py` | Protections anti-manipulation, structure de marché |
| `economic_calendar.py` | Calendrier économique, filtre news |
| `learning_store.py` | Mémoire agent, trades, stats, patterns |
| `runtime_db.py` | SQLite : réglages + échantillons |
| `telegram_notifier.py` | Notifications Telegram (optionnel) |
| `control_panel.py` | Dashboard web (HTML/JS/CSS embarqué) |
| `dashboard.py` | Serveur HTTP pour le dashboard |

## Paires actives

`XAUUSDm`, `BTCUSDm`, `EURUSDm` — 1 position max par paire, 3 positions globales max.

## Démarrage rapide

### 1. Prérequis
- Python 3.13+ avec venv activé
- MT5 Exness ouvert (AutoTrading ON)
- Ollama installé avec `qwen2.5:3b`

### 2. Lancer un cycle
```powershell
.\.venv\Scripts\python.exe run_bot.py
```

### 3. Dashboard temps réel
```powershell
.\.venv\Scripts\python.exe dashboard.py
```
Ouvre http://localhost:8765

### 4. Mode continu
```powershell
.\.venv\Scripts\python.exe run_bot.py daemon
```

### 5. Les deux en même temps
```powershell
.\start_local.ps1
```

## Money Management

- Risque max par trade : 2% du solde (hard cap 5%)
- SL calculé depuis l'ATR, ajusté si le risque dépasse le budget
- Volume calculé via `pip_value_per_lot` réel de MT5
- Ratio RR minimum maintenu ≥ 1.5

## Fonctionnalités

- Rotation automatique des paires dans le cockpit
- Réconciliation automatique des trades fermés par SL/TP sur MT5
- Filtre ML (bloque si proba < 35% avec assez de données)
- Mémoire de patterns gagnants/perdants
- Cooldown entre signaux
- Guard RR faible (risque réduit ×0.6)

## Sécurité

- Aucun appel API cloud
- Aucun broker externe
- MT5 local uniquement + Ollama localhost
- exécution réelle désactivée par défaut
- apprentissage stocké localement dans data/local_runtime.db

---

## Notes pratiques

- symbole par défaut: XAUUSDm
- mode le plus sûr: paper mode
- pour activer le trading réel démo, utilise l'interface locale quand tu es prêt
- les résultats et l'apprentissage restent sur la machine

