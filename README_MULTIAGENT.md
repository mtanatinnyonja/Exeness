# 🤖 SYSTÈME MULTI-AGENT DÉCENTRALISÉ — Exeness Trading

Votre bot a été transformé en **système multi-agent autonome**.

## 🚀 Démarrage rapide

```bash
python start_trading_agents.py
```

Ou:

```bash
python agents_runtime.py
```

**Arrêt:** `Ctrl+C`

---

## 📊 Architecture

**5 agents autonomes** communiquent via un **bus de messages asynchrone**:

```
┌──────────────────────────────────────┐
│        MessageBus (Async)            │
└──────────────────────────────────────┘
       ↓    ↓    ↓    ↓    ↓
    📊  ⚠️  🎯  🚀  👁️
   Analyst Risk Decision Exec Guardian
```

### Agents:

| Agent | Rôle | Boucle |
|-------|------|--------|
| **AnalystAgent** | Scanne marché, trouve signaux | 30s |
| **RiskAgent** | Évalue risques, approuve/bloque | Auto |
| **DecisionAgent** | Synthétise, décide final | Auto |
| **ExecutionAgent** | Exécute ordres, limite positions | Auto |
| **GuardianAgent** | Surveille positions, détecte arrêts | 5s |

---

## ✅ Tests

Valider l'installation:

```bash
python checklist_system.py       # Check global
python validate_imports.py       # Check imports
python test_agents_framework.py  # Test communication
python test_multiagent_flow.py   # Test flux complet
```

**Tous les tests doivent afficher:** `✅ PASS`

---

## 📁 Structure des fichiers

### Framework & Agents (15 fichiers)
- `agent_framework.py` — Base Agent + MessageBus
- `*_agent.py` — 5 agents (analyst, risk, decision, execution, guardian)
- `agents_runtime.py` — Lanceur
- `start_trading_agents.py` — Script de démarrage

### Tests (4 fichiers)
- `test_*` — Tests
- `checklist_system.py` — Validation complète
- `validate_imports.py` — Check imports

### Documentation (3 fichiers)
- `ARCHITECTURE_MULTIAGENT.py` — Vue d'ensemble
- `MIGRATION_GUIDE.py` — Guide complet
- `SUMMARY_COMPLETE.py` — Résumé

### Modules existants (réutilisés)
- `signal_engine.py` ✅
- `smart_strategies.py` ✅
- `market_protection.py` ✅
- `economic_calendar.py` ✅
- `circuit_breaker.py` ✅
- `mt5_bridge.py` ✅
- `audit_logger.py` ✅
- `learning_store.py` ✅

### Code mort (archivé)
- `_backup/trade_orchestrator.old.py` (orchestrateur)
- `_backup/agent_core.old.py` (TradingAgent)
- `_backup/README_ARCHIVAL.md` (explications)

---

## 🔍 Monitoring

Chaque agent log ses actions en temps réel:

```
[2026-05-02T11:18:06] INFO | AnalystAgent   | 📊 EURUSD: Signal BUY (4/5)
[2026-05-02T11:18:06] INFO | RiskAgent      | ✅ EURUSD: APPROUVÉ
[2026-05-02T11:18:07] INFO | DecisionAgent  | 🎯 EURUSD: DÉCISION BUY
[2026-05-02T11:18:07] INFO | ExecutionAgent | 🚀 EURUSD: BUY exécuté
[2026-05-02T11:18:07] INFO | GuardianAgent  | 👁️  EURUSD: EN SURVEILLANCE
```

---

## ⚙️ Configuration

Aucun changement dans `settings.py` nécessaire.

Les agents lisent automatiquement:
- `INSTRUMENTS`
- `PRIMARY_TIMEFRAME`
- `CONFIRM_TIMEFRAME`
- `MAX_RISK_PER_TRADE`
- `MAX_OPEN_POSITIONS`

---

## ✨ Avantages de cette architecture

| Ancien (Orchestrateur) | Nouveau (Multi-agent) |
|--|--|
| ❌ Séquentiel | ✅ Parallèle (async) |
| ❌ Bloquant | ✅ Non-bloquant |
| ❌ Single point of failure | ✅ Résilient |
| ❌ Difficile à tester | ✅ Agents isolés |
| ❌ Couplé | ✅ Découplé (messages) |

---

## 🐛 Troubleshooting

**"ImportError: No module named..."**
- Vérifier: `python validate_imports.py`

**Les agents ne démarrent pas**
- Vérifier: `python checklist_system.py`
- Vérifier MT5 et Ollama accessibles

**Les messages ne circulent pas**
- Vérifier logs (timestamps)
- Vérifier que agents sont abonnés aux bons event_types

---

## 📚 Documentation

- [Architecture complète](ARCHITECTURE_MULTIAGENT.py)
- [Guide de migration](MIGRATION_GUIDE.py)
- [Résumé complet](SUMMARY_COMPLETE.py)

---

## 🎯 Prochaines étapes (optionnel)

1. **PortfolioAgent** — Gère corrélations entre positions
2. **LearningAgent** — Améliore signaux
3. **Dashboard** — Web monitoring
4. **Persistence** — Récupération après crash

---

## ✅ Status

- **Framework:** ✅ Testé
- **Agents:** ✅ 5 agents autonomes
- **Communication:** ✅ MessageBus asynchrone
- **Tests:** ✅ Tous passés
- **Documentation:** ✅ Complète
- **Production:** ✅ PRÊT

---

**Développé avec ❤️ pour l'autonomie des agents IA**

`python start_trading_agents.py` → C'est parti! 🚀
