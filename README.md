# Robot MT5 Local

Système pratique et fiable en mode local:
- MT5 / Exness détecté directement
- apprentissage local avec SQLite
- mémoire persistante
- moteur IA local ultra léger
- option Ollama en localhost uniquement

---

## Fichiers principaux

- settings.py → configuration
- run_bot.py → lancement
- trade_orchestrator.py → logique principale
- mt5_bridge.py → connexion MT5 / paper mode
- local_llm.py → intelligence locale
- learning_store.py → mémoire persistante
- runtime_db.py → base SQLite et réglages
- control_panel.py → interface web locale
- signal_engine.py → indicateurs et score

---

## Démarrage rapide

### 1. Vérifier MT5
Ouvre ton terminal MT5 Exness en démo.

### 2. Lancer un cycle
```powershell
.\.venv\Scripts\python.exe run_bot.py once
```

### 3. Voir l'état
```powershell
.\.venv\Scripts\python.exe run_bot.py status
```

### 4. Lancer le tableau de bord
```powershell
.\.venv\Scripts\python.exe control_panel.py
```
Puis ouvre http://localhost:8080

---

## Mode continu

```powershell
.\.venv\Scripts\python.exe run_bot.py daemon
```

---

## IA locale recommandée

Par défaut, le robot tourne déjà en mode local embarqué, sans internet.

Si tu veux un vrai petit LLM local, le meilleur compromis léger/fiable pour cette machine est:
- modèle recommandé: llama3.2:3b
- runtime local: Ollama
- endpoint autorisé: localhost uniquement

Exemple après installation d'Ollama:
```powershell
ollama pull llama3.2:3b
```
Ensuite, dans l'interface:
- moteur IA = ollama
- modèle local = llama3.2:3b

---

## Sécurité actuelle

- aucun appel API cloud dans le projet
- aucun broker externe cloud
- uniquement MT5 local et localhost pour le LLM
- exécution réelle désactivée par défaut
- apprentissage stocké localement dans data/local_runtime.db

---

## Notes pratiques

- symbole par défaut: XAUUSDm
- mode le plus sûr: paper mode
- pour activer le trading réel démo, utilise l'interface locale quand tu es prêt
- les résultats et l'apprentissage restent sur la machine

