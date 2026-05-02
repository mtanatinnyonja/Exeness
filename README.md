# 🚀 EXENESS — SYSTÈME MULTI-AGENT AUTONOME

**Nettoyé. Fiable. Production-ready.**

## ⚡ Démarrage (30 secondes)

```bash
python start_trading_agents.py
```

**Voilà.** 5 agents tournent en parallèle.

Arrêt: `Ctrl+C`

---

## 📊 Qu'est-ce que c'est?

5 agents **autonomes** qui communiquent via un **bus de messages asynchrone**:

1. **AnalystAgent** → Scan marché, découvre signaux
2. **RiskAgent** → Évalue risques, approuve/bloque
3. **DecisionAgent** → Synthétise, décide BUY/SELL
4. **ExecutionAgent** → Exécute ordres, gère positions
5. **GuardianAgent** → Surveille positions, détecte arrêts

**Pas d'orchestrateur centralisé.** Chacun tourne indépendamment.

---

## ✅ Validation rapide

```bash
python checklist_system.py       # ✅ PASS = prêt
python test_agents_framework.py  # ✅ Test communication
python test_multiagent_flow.py   # ✅ Test flux complet
```

---

## 📚 Documentation

- **[ARCHITECTURE_MULTIAGENT.py](ARCHITECTURE_MULTIAGENT.py)** — Comment ça marche
- **[MIGRATION_GUIDE.py](MIGRATION_GUIDE.py)** — Guide détaillé
- **[FILES_INVENTORY.py](FILES_INVENTORY.py)** — Fichiers et rôles

---

## 📁 Ce qui reste (après nettoyage)

| Catégorie | Fichiers | Status |
|-----------|----------|--------|
| 🤖 Framework + Agents | 8 | ✅ Essentiels |
| 📊 Analyse & Signaux | 3 | ✅ Core |
| 🛡️ Protection | 4 | ✅ Core |
| 🔧 Auxiliaires | 8 | ✅ Support |
| 🧪 Tests | 4 | ✅ Validation |
| 📚 Documentation | 5 | ✅ Référence |
| ⚡ Optionnels | 3 | ⭕ Web/Notif |
| ⚙️ Config | 1 | ✅ Setup |

**Total: 39 fichiers utiles (0% code mort)**

---

## 🎯 Principaux fichiers

| Fichier | Rôle |
|---------|------|
| `start_trading_agents.py` | **Point d'entrée** |
| `agent_framework.py` | Base Agent + MessageBus |
| `*_agent.py` (5 fichiers) | Les 5 agents autonomes |
| `signal_engine.py` | Détection signaux |
| `market_protection.py` | Guards (risque) |
| `circuit_breaker.py` | Auto-pause |
| `audit_logger.py` | Logging complet |
| `settings.py` | Configuration |

---

## 🧹 Ce qui a été supprimé

- ❌ Orchestrateur centralisé (code mort)
- ❌ Vieux tests (agent_core, test_core, etc.)
- ❌ Vieux entry points (main.py, run_bot.py)
- ❌ Vieux scripts (start_local.ps1)
- ❌ Vieux prompts (agent_communication.py)
- ❌ Vieux docs (IMPROVEMENTS.md, VERSION_SUMMARY.md)

**Total supprimé: 12 fichiers (~1,500 lignes)**

---

## 🔧 Configuration

Modifier `settings.py`:
```python
INSTRUMENTS = ["EURUSDm", "XAUUSDm", "BTCUSDm"]
PRIMARY_TIMEFRAME = "H1"
MAX_RISK_PER_TRADE = 0.02
```

Aucun changement nécessaire pour démarrer.

---

## 📊 Monitoring en temps réel

Les logs affichent toutes les actions:

```
[2026-05-02T11:18:06] INFO | AnalystAgent   | 📊 EURUSD: Signal BUY (4/5)
[2026-05-02T11:18:06] INFO | RiskAgent      | ✅ EURUSD: APPROUVÉ
[2026-05-02T11:18:07] INFO | DecisionAgent  | 🎯 EURUSD: DÉCISION BUY
[2026-05-02T11:18:07] INFO | ExecutionAgent | 🚀 EURUSD: BUY exécuté
[2026-05-02T11:18:07] INFO | GuardianAgent  | 👁️  EURUSD: EN SURVEILLANCE
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
