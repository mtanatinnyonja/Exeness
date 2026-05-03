# � Exeness — Agent IA XAUUSDm spécialisé (MT5 + LLM local Ollama)

Exeness est un **système multi-agents IA** Python 100 % local, composé de 5 agents autonomes spécialisés sur **XAUUSDm uniquement**. Chaque décision de trade passe par un **LLM local (Ollama)** qui raisonne sur les signaux techniques avant d'autoriser une position. Sans LLM, aucune position n'est ouverte — c'est intentionnel : ce n'est pas un bot à règles, c'est un agent IA.

---

## 📋 Table des matières

1. [Prérequis système](#1--prérequis-système)
2. [Installation pas à pas](#2--installation-pas-à-pas)
3. [Configuration depuis le dashboard](#3--configuration-depuis-le-dashboard)
4. [Paper trading vs trading réel](#4--paper-trading-vs-trading-réel)
5. [Lancer un backtest](#5--lancer-un-backtest)
6. [Architecture des agents](#6--architecture-des-agents)
7. [FAQ — Erreurs courantes](#7--faq--erreurs-courantes)

---

## 1 · Prérequis système

### 🖥️ Système d'exploitation

> ⚠️ **Windows 10 ou Windows 11 obligatoire.**
> La librairie Python `MetaTrader5` n'est disponible que sous Windows.
> Exeness ne fonctionnera pas sous Linux ou macOS.

### 🐍 Python

Python **3.10 ou supérieur** est requis.

```powershell
python --version
# Doit afficher : Python 3.10.x ou 3.11.x ou 3.12.x
```

Si Python n'est pas installé, téléchargez-le sur [python.org](https://www.python.org/downloads/).
Cochez **"Add Python to PATH"** lors de l'installation.

### 📈 MetaTrader 5

- MetaTrader 5 installé sur la machine.
- Un compte broker connecté dans MT5 (démo ou réel).
- Vous pouvez télécharger MT5 depuis votre broker (ex. Exness, ICMarkets…) ou depuis [metatrader5.com](https://www.metatrader5.com).

### 🦙 Ollama — **OBLIGATOIRE**

Ollama est le **cerveau de l'agent IA**. Le `DecisionAgent` interroge le LLM local avant chaque trade. Sans Ollama actif, **aucune position n'est ouverte**.

- Téléchargement : [https://ollama.ai](https://ollama.ai)
- Modèle recommandé (léger) : `qwen2.5:3b`

```bash
# Installer le modèle
ollama pull qwen2.5:3b

# Vérifier qu'Ollama tourne
curl http://127.0.0.1:11434/api/tags
```

> ⚠️ **Ollama doit être démarré avant `launch.py`.** Si le service est arrêté en cours de route, l'agent IA refuse d'ouvrir de nouvelles positions jusqu'au retour du LLM.

---

## 2 · Installation pas à pas

### 2.1 — Cloner le projet

```bash
git clone <URL_DU_REPO>
cd Exeness
```

### 2.2 — Créer un environnement virtuel

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

> ⚠️ Si PowerShell bloque le script avec une erreur de politique d'exécution :
> ```powershell
> Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
> ```

### 2.3 — Installer les dépendances

```bash
pip install -r requirements.txt
```

Packages installés :

| Package | Usage |
|---|---|
| `MetaTrader5` | Connexion au terminal MT5 |
| `requests` | Notifications Telegram et LLM HTTP |
| `numpy` | Calculs d'indicateurs techniques |
| `tqdm` | Barre de progression (optimizer) |

### 2.4 — Configurer MetaTrader 5

> ⚠️ Cette étape est indispensable. Sans elle, aucun ordre ne peut être passé.

Dans le terminal MetaTrader 5 :

1. **Ouvrir MT5** et se connecter à votre compte broker.
2. **Activer Algo Trading** : cliquer sur le bouton `Algo Trading` dans la barre d'outils (il doit être vert ✅).
3. **Autoriser le trading et les DLL** :
   - Aller dans `Outils` → `Options` → onglet `Expert Advisors`.
   - Cocher ✅ `Autoriser le trading algorithmique`.
   - Cocher ✅ `Autoriser les importations DLL`.
4. Cliquer sur **OK**.

### 2.5 — Premier lancement

```bash
python launch.py
```

Vous devriez voir :

```
============================================================
  ⚡  EXENESS — XAUUSDm Specialist
============================================================
🌐  Dashboard  →  http://localhost:8765

🥇 EXENESS XAUUSDm SPECIALIST — $100 DEMO — DÉMARRAGE
====================================================================
✅ 5 agents démarrés en parallèle
```

Arrêt propre : `Ctrl+C`

### 2.6 — Accéder au dashboard

Ouvrir dans votre navigateur :

```
http://localhost:8765
```

> Si le port 8765 est déjà utilisé, vous pouvez en spécifier un autre :
> ```bash
> python launch.py 9000
> ```

---

## 3 · Configuration depuis le dashboard

Toute la configuration se fait **depuis l'interface web** — aucun fichier à éditer en production.

### 🎯 Onglet Paramètres

| Paramètre | Description | Valeur par défaut |
|---|---|---|
| `instrument` | Instrument fixe traité par le bot | `XAUUSDm` |
| `max_risk_per_trade` | Risque max en % du capital par trade | `0.015` (1.5 %) |
| `daily_target` | Objectif de gain journalier en USD | `5.0` |
| `daily_loss_limit` | Limite de perte journalière en USD (négatif) | `-10.0` |
| `max_open_positions` | Nombre max de positions simultanées | `1` |
| `check_interval_minutes` | Fréquence de cycle d'analyse | `5` |

### 🔐 Activer le trading réel

Par sécurité, **les ordres sont désactivés par défaut**.

Pour autoriser l'exécution réelle dans le dashboard :

1. Aller dans l'onglet **Paramètres**.
2. Passer `allow_trade_execution` à `true`.
3. Cliquer sur **Sauvegarder**.

> ⚠️ `allow_trade_execution = true` + Algo Trading activé dans MT5 = ordres réels passés automatiquement.
> Commencez toujours avec un **compte démo**.

### 📱 Configuration Telegram (optionnel)

Dans la section **Telegram Notifications** du dashboard :

| Champ | Description |
|---|---|
| `telegram_enabled` | Activer/désactiver les notifications |
| `telegram_bot_token` | Token fourni par @BotFather |
| `telegram_chat_id` | ID de votre conversation (obtenez-le via @userinfobot) |

Cliquer sur **Tester Telegram** pour envoyer un message de test.

Notifications envoyées automatiquement :
- 📈 Trade ouvert (avec score, RSI, régime marché, ratio R:R)
- 💰 Trade fermé (P&L)
- 🛑 Limite de perte journalière atteinte
- 📊 Résumé quotidien à 22:00 UTC
- 🚨 Erreurs critiques

> Le bouton **🔍 Détails** dans chaque alerte de trade envoie les indicateurs techniques complets (RSI, MACD, ADX, Bollinger, supports/résistances…).

### 🦙 LLM Ollama — **Cerveau de l'agent**

Dans la section LLM du dashboard :

| Paramètre | Description | Défaut |
|---|---|---|
| `local_llm_endpoint` | URL de l'API Ollama | `http://127.0.0.1:11434/api/generate` |
| `local_llm_model` | Modèle Ollama à utiliser | `qwen2.5:3b` |
| `local_llm_timeout` | Timeout en secondes | `300` |

> Le LLM est consulté pour **chaque décision de trade**. Il reçoit : direction, score, spread, régime de marché, session, ratio SL/TP — et répond OUI/NON avec justification. Son raisonnement est logué dans le dashboard.

---

## 4 · Paper trading vs trading réel

### Mode paper (défaut — aucun risque)

Le mode paper simule des ordres sans les envoyer à MT5.

Dans `settings.py` :

```python
PAPER_TRADING = False       # True = broker simulé local
ALLOW_TRADE_EXECUTION = False  # Garde-fou supplémentaire
```

> Avec `PAPER_TRADING = True`, même si `allow_trade_execution` est activé dans le dashboard, aucun ordre ne part vers MT5.

### Mode réel (trading live)

Pour passer en mode réel :

**Étape 1** — Dans `settings.py` (optionnel, le dashboard suffit) :

```python
PAPER_TRADING = False
ALLOW_TRADE_EXECUTION = False  # Laisser False, on active via dashboard
```

**Étape 2** — Dans le dashboard → Paramètres :
- `allow_trade_execution` → `true`

**Étape 3** — Dans MetaTrader 5 :
- Algo Trading doit être actif (bouton vert).

> ⚠️ Le bridge MT5 vérifie que le compte est un **compte démo** (`REQUIRE_DEMO_ACCOUNT = True` par défaut).
> Si vous utilisez un compte réel, changez ce paramètre dans `settings.py` en connaissance de cause.

### Résumé des modes

| Mode | PAPER_TRADING | allow_trade_execution | Effet |
|---|---|---|---|
| Paper simulé | `True` | `False` ou `True` | Ordres simulés localement, aucun envoi MT5 |
| MT5 lecture seule | `False` | `False` | Analyse et signaux, aucun ordre |
| MT5 trading réel | `False` | `True` | Ordres réels envoyés à MT5 |

---

## 5 · Lancer un backtest

Le backtest charge les données historiques XAUUSDm depuis MT5 et simule le comportement du bot.

```bash
python backtest.py XAUUSDm 30
```

Syntaxe :

```
python backtest.py <INSTRUMENT> <JOURS>
```

Exemples :

```bash
# Gold sur 10 jours
python backtest.py XAUUSDm 10

# Gold sur 30 jours
python backtest.py XAUUSDm 30
```

> Le nom de l'instrument doit correspondre exactement à celui affiché dans MT5. Dans cette version spécialisée, utilisez `XAUUSDm`.

### Optimiseur de paramètres

Pour trouver les meilleurs paramètres (RSI, MA, seuils) par grid search :

```bash
python optimizer.py XAUUSDm 30
```

Les meilleurs paramètres sont automatiquement sauvegardés dans `data/optimized_params.json` si le Sharpe ratio est amélioré.

---

## 6 · Architecture des agents

### 5 agents autonomes

```
AnalystAgent → [signal] → RiskAgent → [risk_decision] → DecisionAgent → [buy/sell_signal] → ExecutionAgent
                                                                                                      ↑
                                                                                               GuardianAgent (surveillance positions)
```

| Agent | Rôle |
|---|---|
| **AnalystAgent** | Analyse XAUUSDm toutes les 15s, publie des signaux (score 1-5) |
| **RiskAgent** | Évalue chaque signal : spread, ratio R:R, qualité, news |
| **DecisionAgent** | Décision finale après validation risque, cooldown et confiance |
| **ExecutionAgent** | Envoie les ordres à MT5, gère trailing stop et clôtures |
| **GuardianAgent** | Surveille les positions ouvertes, détecte les fermetures MT5 |

### 🛡️ Garde-fous intégrés

| Protection | Détail |
|---|---|
| Warmup 120s | Aucun trade les 2 premières minutes après démarrage |
| Double confirmation | Un signal doit apparaître 2x en 90s avant décision |
| Confiance minimum | Signaux < 55% de confiance ignorés |
| 1 position max | Hard guard : pas de pyramidage |
| Circuit Breaker | Pause auto après 3 pertes consécutives (2h) ou dépassement perte journalière (24h) |
| Spread guard | Rejet si spread XAU trop élevé (> 8p en normal, > 6p en scalping) |
| News filter | Blocage avant événements économiques majeurs |
| Score minimum | R:R minimum 1.5, quality_score minimum 0.4 |

### 📁 Fichiers du projet

```
Exeness/
│
├── launch.py               ← Point d'entrée unique
├── agents_runtime.py       ← Orchestre les 5 agents
├── agent_framework.py      ← Classe Agent + MessageBus asyncio
│
├── analyst_agent.py        ← Scanner de marché
├── risk_agent.py           ← Évaluateur de risque
├── decision_agent.py       ← Décideur final
├── execution_agent.py      ← Exécution MT5
├── guardian_agent.py       ← Surveillance positions
│
├── control_panel.py        ← Dashboard web (HTTP)
├── mt5_bridge.py           ← Connexion MetaTrader 5
├── signal_engine.py        ← Indicateurs techniques (RSI, MACD, BB, ADX…)
├── smart_strategies.py     ← Stratégies SMC, HTF, sessions
├── circuit_breaker.py      ← Coupe-circuit automatique
├── market_protection.py    ← Protections (news, spread, régime)
├── telegram_notifier.py    ← Notifications Telegram enrichies
├── backtest.py             ← Backtest historique
├── optimizer.py            ← Grid search paramètres
├── runtime_db.py           ← SQLite settings runtime
├── learning_store.py       ← Mémoire locale d'apprentissage
├── settings.py             ← Constantes de configuration
│
└── data/
    ├── local_runtime.db         ← Paramètres runtime (SQLite)
    ├── scan_results.json        ← Résultats dernière analyse
    ├── agents_heartbeat.json    ← Statut temps réel des agents
    ├── agent_memory.json        ← Statistiques d'apprentissage
    ├── trades_history.json      ← Historique des trades
    ├── optimized_params.json    ← Meilleurs paramètres optimiseur
    └── audit/
        └── audit_YYYY-MM-DD.jsonl  ← Logs complets horodatés
```

---

## 7 · FAQ — Erreurs courantes

### ❌ `MT5 not initialized` / `MT5 non initialisé`

**Causes possibles :**
- MetaTrader 5 n'est pas lancé.
- Aucun compte n'est connecté dans MT5.
- Algo Trading ou DLL non autorisés.
- Chemin d'installation MT5 non standard.

**Solutions :**

1. Lancer MetaTrader 5 manuellement et se connecter.
2. Vérifier que le bouton **Algo Trading** est vert dans MT5.
3. Aller dans `Outils → Options → Expert Advisors` et cocher les deux cases.
4. Si MT5 est installé dans un chemin non standard, renseigner dans `settings.py` :

```python
MT5_TERMINAL_PATH = "C:/Program Files/MetaTrader 5/terminal64.exe"
```

---

### ❌ `No module named 'MetaTrader5'`

Le package n'est pas installé dans l'environnement actif.

```bash
pip install MetaTrader5
```

> ⚠️ Ce package **ne fonctionne que sous Windows**. Sous Linux/macOS, il est introuvable par design.
> Vérifiez que votre venv est bien activé avant d'installer.

---

### ❌ `retcode 10027` / `auto-trading désactivé`

Le terminal MT5 a désactivé le trading algorithmique côté client.

**Solution :**
1. Dans MetaTrader 5, cliquer sur le bouton **Algo Trading** (barre d'outils) → il doit devenir vert.
2. Aller dans `Outils → Options → Expert Advisors` et cocher `Autoriser le trading algorithmique`.
3. Relancer Exeness (l'agent reprend automatiquement après 2 minutes).

---

### ❌ Circuit Breaker actif — impossible d'ouvrir de nouveaux trades

Le circuit breaker se déclenche automatiquement dans 3 situations :

| Déclencheur | Durée de pause |
|---|---|
| 3 pertes consécutives | 2 heures |
| Perte journalière > `daily_loss_limit` | 24 heures |
| Spread spike anormal (× 3 la normale) | 15 minutes |

**Vérifier son état :**

```bash
python -c "from circuit_breaker import CircuitBreaker; cb=CircuitBreaker(); print(cb.get_status())"
```

**Reset manuel (si vous voulez reprendre manuellement avant l'expiration) :**

```bash
python -c "from circuit_breaker import CircuitBreaker; cb=CircuitBreaker(); cb.reset_daily(); print('Reset OK ->', cb.get_status())"
```

> ⚠️ Resetez le circuit breaker seulement si vous avez compris et corrigé la cause du déclenchement.

---

### ❌ Aucun signal généré / bot inactif

1. Vérifier que MT5 est connecté et que le marché est ouvert (cf. heure UTC).
2. Vérifier dans MT5 que `XAUUSDm` est bien visible dans Market Watch.
3. Consulter les logs dans `data/agent_memory.json` (champ `session_log`).
4. Augmenter temporairement le seuil `min_broadcast_score` si les signaux sont trop faibles (défaut 3/5).

---

### ❌ Notifications Telegram silencieuses

1. Vérifier que `telegram_enabled = true` dans le dashboard.
2. Utiliser le bouton **Tester Telegram** pour diagnostiquer.
3. Vérifier le bot token (format `123456789:ABCdef...`) et le chat_id.
4. Le chat_id doit être l'ID **numérique** de la conversation (pas le @username).

---

## 🚀 Commandes de référence

```bash
# Démarrage principal
python launch.py

# Démarrage sur un port alternatif
python launch.py 9000

# Backtest sur 30 jours
python backtest.py XAUUSDm 30

# Optimisation des paramètres techniques
python optimizer.py XAUUSDm 30

# Vérification rapide du circuit breaker
python -c "from circuit_breaker import CircuitBreaker; print(CircuitBreaker().get_status())"

# Reset du circuit breaker
python -c "from circuit_breaker import CircuitBreaker; cb=CircuitBreaker(); cb.reset_daily(); print('Reset OK')"
```

---

## ⚠️ Avertissements importants

> ⚠️ **Le trading algorithmique comporte un risque de perte en capital.**
> Commencez toujours avec un compte démo. Validez vos paramètres de risque avant toute exécution live.

> ⚠️ `allow_trade_execution = true` + Algo Trading MT5 actif = **ordres réels passés automatiquement**. Ne laissez pas le bot sans surveillance lors des premiers jours de trading réel.

> ⚠️ Les performances passées (backtest) ne garantissent pas les performances futures.
