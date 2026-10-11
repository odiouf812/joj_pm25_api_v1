# JOJ Dakar 2026 · Prévision PM2,5 (LSTM) — API FastAPI

Déploiement du notebook `lstm_pm2_5_ci_pr3_dose_1026.ipynb` sous forme d'API + interface web.

**Parcours en 5 étapes** : 1. Upload Excel → 2. Modèle LSTM → 3. Prévisions (IC 95 %) → 4. Classification → 5. Risques & messages
+ téléchargement (Excel complet, CSV, messages TXT, JSON).

## Lancement

```bash
./run.sh                 # Linux / macOS   (Windows : run.bat)
# ou
docker compose up --build
```
Ouvrir **http://localhost:8000** (interface) · **http://localhost:8000/docs** (API interactive Swagger).

> Utilisez **un seul worker** (l'avancement de l'entraînement est suivi en mémoire).

## Réentraînement automatique
Chaque fichier envoyé (étape 1) est **fusionné** avec l'historique (`data/master.csv`, doublons de dates remplacés
par la valeur la plus récente) ou **remplace** tout (option). Si « Réentraîner automatiquement » est coché, le
LSTM est réentraîné sur l'ensemble des données, puis les prévisions, la classification, les risques et les
messages sont **régénérés**. Le bandeau « Modèle » indique quand le modèle n'est plus à jour.

Format Excel : colonnes `Date` et `PM2.5` (une ligne par jour). Modèle téléchargeable dans l'interface.
Minimum : 90 observations.

## Endpoints principaux
| Méthode | Route | Rôle |
|---|---|---|
| POST | `/api/upload` | Excel/CSV (`file`, `mode`=merge ou replace, `retrain`=true ou false) |
| POST | `/api/train` | (Ré)entraîner (`epochs`) |
| GET  | `/api/status`, `/api/model` | État données / modèle / entraînement |
| POST | `/api/predict` | Prévision `n_days` (1–7, défaut 2) |
| GET  | `/api/forecast`, `/api/classification`, `/api/risks` | Résultats |
| GET  | `/api/download/{xlsx, csv, messages, json}` | Téléchargements |
| POST | `/api/demo-data` | Série **synthétique** pour tester |

Exemple : `curl -F file=@PM2_5.xlsx -F retrain=true http://localhost:8000/api/upload`

## Structure
```
notebook/ notebook de référence (source des calculs)
app/  main.py (routes) · ml.py (LSTM, MC Dropout) · health.py (classes, RR/FA, messages)
      data.py (Excel) · exports.py · config.py (tous les paramètres) · static/ (interface)
data/ models/ outputs/   → données, modèle entraîné, derniers résultats (à persister)
```

## Paramètres (`app/config.py`)
Fenêtre 30 j, 500 simulations, seuils, `COUNTERFACTUAL`, `SN_REFERENCE`, tableau des RR, dates de l'événement.

## Points d'attention (écarts / choix par rapport au notebook)
- `COUNTERFACTUAL = 15` (valeur guide journalière OMS) : référence du calcul RR/FA et seuil du message ; `SN_REFERENCE = 65` sert à la classification et au graphique.
- Message sanitaire : un seul message par jour (cardiovasculaire + respiratoire), émis si PM2,5 prévu > 15 µg/m³ (valeur guide OMS).
- Simulations Monte Carlo exécutées **en lot** (500 trajectoires en parallèle) : même méthode, bien plus rapide.
- Ajout : RMSE/MAE sur les 15 % de séquences non utilisés à l'entraînement.
- Les logos officiels des JOJ ne sont pas inclus (droits) : à ajouter dans `static/index.html`.
