"""Paramètres centraux (repris du notebook lstm_pm2_5_ci_pr3_dose_1026)."""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
MASTER_CSV = DATA_DIR / "master.csv"          # jeu de données cumulé
MODEL_DIR = BASE_DIR / "models"
MODEL_PATH = MODEL_DIR / "lstm_pm25.keras"
META_PATH = MODEL_DIR / "meta.json"
OUT_DIR = BASE_DIR / "outputs"
RESULTS_PATH = OUT_DIR / "results.json"
STATIC_DIR = Path(__file__).resolve().parent / "static"

for _d in (DATA_DIR, UPLOAD_DIR, MODEL_DIR, OUT_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# --- Modèle LSTM ---------------------------------------------------------
SEED = 42
LOOK_BACK = 30
DROPOUT_RATE = 0.2
LEARNING_RATE = 0.001
EPOCHS = 150
BATCH_SIZE = 32
PATIENCE = 15
TRAIN_RATIO = 0.85          # part des séquences utilisée pour l'entraînement
VALIDATION_SPLIT = 0.15     # prise sur la fin du jeu d'entraînement (comme Keras)
MIN_ROWS = LOOK_BACK + 60   # nombre minimal d'observations pour entraîner

# --- Prévision Monte Carlo Dropout ---------------------------------------
DEFAULT_DAYS = 2
MAX_DAYS = 7
N_SIMULATIONS = 500

# --- Indicateurs de santé ------------------------------------------------
COUNTERFACTUAL = 15         # µg/m³ - valeur guide journalière OMS (niveau de référence)
SN_REFERENCE = 65           # µg/m³ - repère réglementaire sénégalais (classification/graphique)
RR_TABLE = [  # RR par 10 µg/m³ et IC 95 %
    {"Outcome": "cardiovasculaires", "ICD10": "I00-I99",
     "RR_unit": 1.0090, "RR_low": 1.0026, "RR_high": 1.0153},
    {"Outcome": "respiratoires", "ICD10": "J00-J99",
     "RR_unit": 1.0057, "RR_low": 1.0033, "RR_high": 1.0082},
]

# --- Événement -----------------------------------------------------------
EVENT = {
    "name": "JOJ Dakar 2026",
    "start": "2026-10-31",
    "end": "2026-11-13",
}
