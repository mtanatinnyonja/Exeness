# 🚀 EXENESS — BOT TRADING MULTI-AGENT AUTONOME

**5 agents IA. 1 dashboard. Connexion MT5 directe.**

---

## ⚡ Démarrage

```bash
python launch.py
```

Dashboard: **http://localhost:8765**  
Arrêt: `Ctrl+C`

---

## 📊 Architecture

5 agents autonomes communiquant via un **bus de messages asynchrone**:

| Agent | Rôle |
|-------|------|
| **AnalystAgent** | Scan marché, génère signaux (score 1-5) |
| **RiskAgent** | Évalue risques, approuve ou bloque |
| **DecisionAgent** | Décision finale BUY/SELL après délibération |
| **ExecutionAgent** | Envoie ordres à MT5, gère positions |
| **GuardianAgent** | Surveille positions ouvertes, détecte SL/TP |

Les agents ne s'appellent pas directement — ils s'envoient des messages et chacun décide.

---

## 🛡️ Garde-fous intégrés

- **Warmup 120s** au démarrage (aucun trade pendant les 2 premières minutes)
- **Double confirmation** : un signal doit apparaître 2x en 90s avant passage en décision
- **Confiance minimum 55%** — les signaux faibles sont ignorés
- **1 position max** simultanée (hard guard)
- **Circuit Breaker** : pause auto si pertes excessives ou erreurs MT5 répétées
- **Anti-spam news** : blocage configurable avant/après événements économiques
- **Spread guard** : rejet si spread trop élevé (XAU/BTC: 30p, autres: 5p)

---

## 🔧 Configuration

Tout se configure depuis le **dashboard** (`/` → onglet Paramètres) :

- Paires préférées, risque par trade, objectif/limite journalière
- Activation du trading réel (`allow_trade_execution`)
- Token + Chat ID Telegram
- Paramètres LLM (Ollama, optionnel)

Pour trader en réel avec MT5 :
1. Activer **"Algo Trading"** dans le terminal MT5
2. Mettre `allow_trade_execution` à `true` dans les paramètres

---

## 📁 Fichiers principaux

| Fichier | Rôle |
|---------|------|
| `launch.py` | **Point d'entrée unique** |
| `agent_framework.py` | Classe de base Agent + MessageBus |
| `analyst_agent.py` | Scanner marché |
| `risk_agent.py` | Évaluateur de risque |
| `decision_agent.py` | Décision finale |
| `execution_agent.py` | Exécution MT5 |
| `guardian_agent.py` | Surveillance positions |
| `control_panel.py` | Dashboard web + API HTTP |
| `mt5_bridge.py` | Connexion MetaTrader 5 |
| `signal_engine.py` | Calcul des signaux techniques |
| `circuit_breaker.py` | Protection auto-pause |
| `market_protection.py` | Guards (news, spread, etc.) |
| `telegram_notifier.py` | Notifications Telegram |
| `audit_logger.py` | Logs JSONL horodatés |
| `runtime_db.py` | Persistance SQLite settings |
| `settings.py` | Constantes de configuration |

---

## 📱 Telegram

Configurable directement depuis le dashboard (Paramètres → Telegram) :
- Activer/désactiver les notifications
- Saisir le Bot Token et le Chat ID
- Bouton **"Tester Telegram"** pour valider la connexion

Événements notifiés : trade ouvert, trade fermé, limite de perte atteinte, résumé journalier, erreurs critiques.

---

## 🗄️ Données

```
data/
  local_runtime.db        ← Settings persistants (SQLite)
  scan_results.json       ← Résultats scanner (mis à jour toutes les 30s)
  agents_heartbeat.json   ← Statut des 5 agents en temps réel
  agent_memory.json       ← Mémoire d'apprentissage
  trades_history.json     ← Historique des trades
  audit/audit_YYYY-MM-DD.jsonl  ← Logs complets
```

---

## ✨ Avantages

| Feature | Avant | Après |
|---------|-------|-------|
| Architecture | Centralisée | Décentralisée |
| Concurrence | Séquentielle | Parallèle (async) |
| Résilience | Non | Oui (agents indépendants) |
| Testabilité | Difficile | Facile (agents isolés) |
| Code mort | Oui | Non |

---

## 🚀 Commandes utiles

```bash
# Démarrage
python start_trading_agents.py

# Validation
python checklist_system.py
python FILES_INVENTORY.py

# Tests
python test_agents_framework.py
python test_multiagent_flow.py
python validate_imports.py
```

---

## ✅ Status

```
✅ Système nettoyé (0% code mort)
✅ Tous les tests passent
✅ 39 fichiers utiles + structurés
✅ Production-ready
```

---

**Prêt?** `python start_trading_agents.py` 🚀
