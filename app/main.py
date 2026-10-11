"""API FastAPI - Prévision PM2.5 (LSTM) · JOJ Dakar 2026."""
from __future__ import annotations

import json
import math
from datetime import datetime

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import config, data, exports, health, ml

app = FastAPI(
    title="JOJ Dakar 2026 · Qualité de l'air (PM2,5)",
    description="Upload Excel → LSTM → prévisions Monte Carlo → classification → risques & messages.",
    version="1.0.0",
)
app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")


def _clean(obj):
    """Remplace NaN/Inf par None pour un JSON valide."""
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean(v) for v in obj]
    return obj


def _json(obj, status=200):
    return JSONResponse(_clean(obj), status_code=status)


def _load_results() -> dict | None:
    if config.RESULTS_PATH.exists():
        return json.loads(config.RESULTS_PATH.read_text(encoding="utf-8"))
    return None


def _require_results() -> dict:
    res = _load_results()
    if res is None:
        raise HTTPException(404, "Aucune prévision disponible. Lancez l'étape 3 (Prévisions).")
    return res


def run_forecast(n_days: int) -> dict:
    fc = ml.forecast(n_days=n_days)
    res = health.build_results(fc)
    res["generated_at"] = datetime.now().isoformat(timespec="seconds")
    res["n_days"] = n_days
    res["n_simulations"] = config.N_SIMULATIONS
    config.RESULTS_PATH.write_text(json.dumps(_clean(res), ensure_ascii=False), encoding="utf-8")
    return res


# --------------------------------------------------------------------------- #
# Pages & configuration
# --------------------------------------------------------------------------- #
@app.get("/", include_in_schema=False)
def index():
    return FileResponse(config.STATIC_DIR / "index.html")


@app.get("/api/config", tags=["Général"])
def get_config():
    return {"event": config.EVENT, "look_back": config.LOOK_BACK,
            "default_days": config.DEFAULT_DAYS, "max_days": config.MAX_DAYS,
            "n_simulations": config.N_SIMULATIONS, "min_rows": config.MIN_ROWS,
            "counterfactual": config.COUNTERFACTUAL, "sn_reference": config.SN_REFERENCE,
            "epochs": config.EPOCHS}


@app.get("/api/status", tags=["Général"])
def status():
    df = data.load_master()
    return _json({
        "data": data.summary(df),
        "model": ml.model_info(),
        "training": ml.STATE,
        "has_results": config.RESULTS_PATH.exists(),
    })


# --------------------------------------------------------------------------- #
# 1. Données
# --------------------------------------------------------------------------- #
@app.post("/api/upload", tags=["1. Données"])
async def upload(
    file: UploadFile = File(...),
    mode: str = Form("merge"),          # merge | replace
    retrain: bool = Form(True),         # réentraînement automatique
):
    """Charge un fichier Excel (Date, PM2.5) et réentraîne le modèle si demandé."""
    if ml.is_training():
        raise HTTPException(409, "Un entraînement est en cours, réessayez dans un instant.")
    if mode not in ("merge", "replace"):
        raise HTTPException(400, "mode doit valoir 'merge' ou 'replace'.")
    content = await file.read()
    try:
        new = data.parse_upload(content, file.filename or "")
    except data.DataError as exc:
        raise HTTPException(400, str(exc)) from exc

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    (config.UPLOAD_DIR / f"{stamp}_{file.filename}").write_bytes(content)
    master, stats = data.merge_into_master(new, mode)

    training_started, note = False, None
    if retrain:
        try:
            ml.start_training(on_done=lambda: run_forecast(
                (_load_results() or {}).get("n_days", config.DEFAULT_DAYS)))
            training_started = True
        except data.DataError as exc:
            note = str(exc)
    return _json({"ok": True, "filename": file.filename, "dropped_rows": new.attrs.get("dropped", 0),
                  **stats, "summary": data.summary(master),
                  "training_started": training_started, "note": note})


@app.post("/api/demo-data", tags=["1. Données"])
def demo_data(retrain: bool = Form(False)):
    """Charge une série SYNTHÉTIQUE pour tester l'application."""
    if ml.is_training():
        raise HTTPException(409, "Un entraînement est en cours.")
    master, stats = data.merge_into_master(data.make_demo_data(), "replace")
    if retrain:
        ml.start_training()
    return _json({"ok": True, **stats, "summary": data.summary(master), "training_started": retrain})


@app.get("/api/history", tags=["1. Données"])
def history(last_n: int = Query(120, ge=10, le=5000)):
    return _json({"history": data.history_records(data.load_master(), last_n)})


@app.get("/api/template", tags=["1. Données"])
def template():
    return Response(data.template_xlsx(),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": 'attachment; filename="modele_PM2_5.xlsx"'})


# --------------------------------------------------------------------------- #
# 2. Modèle
# --------------------------------------------------------------------------- #
@app.post("/api/train", tags=["2. Modèle"])
def train(epochs: int = Form(config.EPOCHS)):
    """(Ré)entraîne le LSTM sur l'ensemble des données cumulées."""
    try:
        ml.start_training(epochs=max(1, min(epochs, 500)), on_done=lambda: run_forecast(
            (_load_results() or {}).get("n_days", config.DEFAULT_DAYS)))
    except data.DataError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"ok": True, "message": "Entraînement lancé."}


@app.get("/api/model", tags=["2. Modèle"])
def model_info():
    return _json({"model": ml.model_info(), "training": ml.STATE})


# --------------------------------------------------------------------------- #
# 3. Prévisions · 4. Classification · 5. Risques & messages
# --------------------------------------------------------------------------- #
@app.post("/api/predict", tags=["3. Prévisions"])
def predict(n_days: int = Form(config.DEFAULT_DAYS)):
    """Prévision Monte Carlo Dropout (IC 95 %) + classification + risques + messages."""
    if ml.is_training():
        raise HTTPException(409, "Entraînement en cours.")
    if not 1 <= n_days <= config.MAX_DAYS:
        raise HTTPException(400, f"n_days doit être compris entre 1 et {config.MAX_DAYS}.")
    try:
        return _json(run_forecast(n_days))
    except data.DataError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/forecast", tags=["3. Prévisions"])
def get_forecast():
    res = _require_results()
    return _json({"generated_at": res["generated_at"], "n_days": res["n_days"],
                  "forecast": res["forecast"]})


@app.get("/api/classification", tags=["4. Classification"])
def get_classification():
    res = _require_results()
    return _json({"forecast": res["forecast"], "scale": res["scale"], "levels": res["levels"]})


@app.get("/api/risks", tags=["5. Risques et messages"])
def get_risks():
    res = _require_results()
    return _json({"health": res["health"], "messages": res["messages"], "counterfactual": res["counterfactual"],
                  "sn_reference": res["sn_reference"]})


# --------------------------------------------------------------------------- #
# Téléchargements
# --------------------------------------------------------------------------- #
@app.get("/api/download/{kind}", tags=["Téléchargements"])
def download(kind: str):
    """kind = xlsx (rapport complet) | csv (prévisions) | messages (txt) | json"""
    res = _require_results()
    stamp = datetime.now().strftime("%Y%m%d")
    if kind == "xlsx":
        body, mt, name = exports.to_xlsx(res), (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"), \
            f"JOJ2026_PM25_previsions_risques_{stamp}.xlsx"
    elif kind == "csv":
        body, mt, name = exports.to_csv(res), "text/csv", f"JOJ2026_PM25_previsions_{stamp}.csv"
    elif kind == "messages":
        body, mt, name = (exports.messages_txt(res), "text/plain; charset=utf-8",
                          f"JOJ2026_PM25_messages_{stamp}.txt")
    elif kind == "json":
        body, mt, name = (json.dumps(res, ensure_ascii=False, indent=2).encode(),
                          "application/json", f"JOJ2026_PM25_{stamp}.json")
    else:
        raise HTTPException(404, "Type inconnu : xlsx, csv, messages ou json.")
    return Response(body, media_type=mt,
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})
