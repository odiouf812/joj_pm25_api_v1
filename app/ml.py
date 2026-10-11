"""LSTM PM2.5 : entraînement, état d'avancement et prévision Monte Carlo Dropout."""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")

import numpy as np
import pandas as pd

from . import config
from .data import DataError, load_master

_lock = threading.Lock()
_model_cache = {"model": None, "mtime": None}

STATE: dict = {
    "status": "idle",      # idle | running | done | error
    "epoch": 0, "epochs": config.EPOCHS,
    "logs": [], "message": "", "started_at": None, "finished_at": None,
}


# --------------------------------------------------------------------------- #
# Utilitaires
# --------------------------------------------------------------------------- #
def create_sequences(data: np.ndarray, look_back: int):
    n = len(data) - look_back
    X = np.empty((n, look_back))
    y = np.empty(n)
    for i in range(n):
        X[i, :] = data[i:i + look_back]
        y[i] = data[i + look_back]
    return X, y


def build_model(look_back: int):
    import keras
    from keras import layers
    model = keras.Sequential([
        keras.Input(shape=(look_back, 1)),
        layers.LSTM(64, return_sequences=True),
        layers.Dropout(config.DROPOUT_RATE),
        layers.LSTM(32),
        layers.Dropout(config.DROPOUT_RATE),
        layers.Dense(16, activation="relu"),
        layers.Dense(1),
    ])
    model.compile(optimizer=keras.optimizers.Adam(learning_rate=config.LEARNING_RATE),
                  loss="mse", metrics=["mae"])
    return model


def load_meta() -> dict | None:
    if not config.META_PATH.exists():
        return None
    return json.loads(config.META_PATH.read_text(encoding="utf-8"))


def model_info() -> dict:
    meta = load_meta()
    df = load_master()
    if meta is None:
        return {"trained": False}
    outdated = df is not None and (
        len(df) != meta["n_rows"] or df["Date"].max().strftime("%Y-%m-%d") != meta["data_end"])
    return {"trained": True, "outdated": bool(outdated), **meta}


def get_model():
    import keras
    if not config.MODEL_PATH.exists():
        raise DataError("Aucun modèle entraîné. Lancez d'abord l'entraînement (étape 2).")
    mtime = config.MODEL_PATH.stat().st_mtime
    if _model_cache["model"] is None or _model_cache["mtime"] != mtime:
        _model_cache["model"] = keras.models.load_model(config.MODEL_PATH)
        _model_cache["mtime"] = mtime
    return _model_cache["model"]


# --------------------------------------------------------------------------- #
# Entraînement
# --------------------------------------------------------------------------- #
def is_training() -> bool:
    return STATE["status"] == "running"


def start_training(epochs: int | None = None, on_done=None) -> None:
    """Lance l'entraînement dans un thread (réentraînement complet sur le master)."""
    with _lock:
        if is_training():
            raise RuntimeError("Un entraînement est déjà en cours.")
        df = load_master()
        if df is None or len(df) < config.MIN_ROWS:
            raise DataError(
                f"Données insuffisantes : {0 if df is None else len(df)} observations "
                f"(minimum {config.MIN_ROWS}).")
        STATE.update(status="running", epoch=0, epochs=epochs or config.EPOCHS, logs=[],
                     message="Préparation des données…", started_at=time.time(), finished_at=None)
    threading.Thread(target=_train, args=(df.copy(), STATE["epochs"], on_done), daemon=True).start()


def _train(df: pd.DataFrame, epochs: int, on_done) -> None:
    try:
        import keras

        keras.utils.set_random_seed(config.SEED)
        values = df["PM2.5"].to_numpy(dtype="float64")
        min_val, max_val = float(values.min()), float(values.max())
        if max_val == min_val:
            raise DataError("La série est constante : entraînement impossible.")
        scaled = (values - min_val) / (max_val - min_val)

        X, y = create_sequences(scaled, config.LOOK_BACK)
        X = X.reshape(X.shape[0], config.LOOK_BACK, 1)
        split_idx = int(np.floor(X.shape[0] * config.TRAIN_RATIO))
        X_train, y_train = X[:split_idx], y[:split_idx]
        X_test, y_test = X[split_idx:], y[split_idx:]

        model = build_model(config.LOOK_BACK)
        STATE["message"] = "Entraînement du LSTM…"

        class Progress(keras.callbacks.Callback):
            def on_epoch_end(self, epoch, logs=None):
                logs = logs or {}
                STATE["epoch"] = epoch + 1
                STATE["logs"].append({
                    "epoch": epoch + 1,
                    "loss": float(logs.get("loss", np.nan)),
                    "val_loss": float(logs.get("val_loss", np.nan)),
                })

        early_stop = keras.callbacks.EarlyStopping(
            monitor="val_loss", patience=config.PATIENCE, restore_best_weights=True)
        model.fit(X_train, y_train, validation_split=config.VALIDATION_SPLIT,
                  epochs=epochs, batch_size=config.BATCH_SIZE,
                  callbacks=[early_stop, Progress()], verbose=0)

        # Évaluation sur la part non utilisée à l'entraînement (échelle d'origine)
        metrics = {"rmse": None, "mae": None, "n_test": int(len(X_test))}
        if len(X_test) > 0:
            pred = model(X_test, training=False).numpy().ravel()
            err = (pred - y_test) * (max_val - min_val)
            metrics.update(rmse=round(float(np.sqrt(np.mean(err ** 2))), 2),
                           mae=round(float(np.mean(np.abs(err))), 2))

        model.save(config.MODEL_PATH)
        _model_cache.update(model=None, mtime=None)
        meta = {
            "trained_at": datetime.now().isoformat(timespec="seconds"),
            "n_rows": int(len(df)),
            "data_start": df["Date"].min().strftime("%Y-%m-%d"),
            "data_end": df["Date"].max().strftime("%Y-%m-%d"),
            "min_val": min_val, "max_val": max_val,
            "look_back": config.LOOK_BACK,
            "epochs_run": len(STATE["logs"]),
            "best_val_loss": min((l["val_loss"] for l in STATE["logs"]), default=None),
            "metrics": metrics,
            "loss_history": STATE["logs"],
            "n_params": int(model.count_params()),
        }
        config.META_PATH.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        STATE.update(status="done", message="Modèle entraîné avec succès.",
                     finished_at=time.time())
        if on_done:
            on_done()
    except Exception as exc:  # noqa: BLE001
        STATE.update(status="error", message=str(exc), finished_at=time.time())


# --------------------------------------------------------------------------- #
# Prévision Monte Carlo Dropout (dropout actif, simulations en lot)
# --------------------------------------------------------------------------- #
def forecast(n_days: int = config.DEFAULT_DAYS,
             n_simulations: int = config.N_SIMULATIONS) -> pd.DataFrame:
    meta = load_meta()
    df = load_master()
    if meta is None or df is None:
        raise DataError("Aucun modèle entraîné. Lancez d'abord l'entraînement (étape 2).")
    model = get_model()
    look_back, min_val, max_val = meta["look_back"], meta["min_val"], meta["max_val"]

    values = df["PM2.5"].to_numpy(dtype="float64")
    scaled = (values - min_val) / (max_val - min_val)
    last = scaled[-look_back:].reshape(1, look_back, 1).astype("float32")

    window = np.repeat(last, n_simulations, axis=0)
    paths = np.empty((n_simulations, n_days))
    for d in range(n_days):
        out = np.asarray(model(window, training=True)).reshape(-1)   # dropout ACTIF
        paths[:, d] = out
        window = np.concatenate([window[:, 1:, :], out.reshape(-1, 1, 1)],
                                axis=1).astype("float32")

    paths = paths * (max_val - min_val) + min_val
    dates = pd.date_range(df["Date"].max() + pd.Timedelta(days=1), periods=n_days, freq="D")
    return pd.DataFrame({
        "Date": dates,
        "Forecast": paths.mean(axis=0),
        "SD": paths.std(axis=0, ddof=1),
        "Lower_95": np.quantile(paths, 0.025, axis=0),
        "Upper_95": np.quantile(paths, 0.975, axis=0),
    })
