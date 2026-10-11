"""Lecture, validation et fusion des fichiers Excel/CSV de PM2.5."""
from __future__ import annotations

import io
import re
from datetime import datetime

import numpy as np
import pandas as pd

from . import config


class DataError(ValueError):
    """Erreur de validation lisible par l'utilisateur."""


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def parse_upload(content: bytes, filename: str) -> pd.DataFrame:
    """Retourne un DataFrame propre [Date, PM2.5] à partir d'un .xlsx/.xls/.csv."""
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    try:
        if ext in ("xlsx", "xlsm", "xls"):
            raw = pd.read_excel(io.BytesIO(content))
        elif ext == "csv":
            raw = pd.read_csv(io.BytesIO(content), sep=None, engine="python")
        else:
            raise DataError("Format non supporté : utilisez un fichier .xlsx (ou .csv).")
    except DataError:
        raise
    except Exception as exc:  # fichier corrompu, etc.
        raise DataError(f"Impossible de lire le fichier : {exc}") from exc

    cols = {_norm(c): c for c in raw.columns}
    date_col = cols.get("date")
    pm_col = next((cols[k] for k in ("pm25", "pm2p5", "pm") if k in cols), None)
    if date_col is None or pm_col is None:
        raise DataError(
            "Colonnes introuvables. Le fichier doit contenir « Date » et « PM2.5 » "
            f"(colonnes détectées : {', '.join(map(str, raw.columns))})."
        )

    df = pd.DataFrame({
        "Date": pd.to_datetime(raw[date_col], errors="coerce", dayfirst=False),
        "PM2.5": pd.to_numeric(
            raw[pm_col].astype(str).str.replace(",", ".", regex=False), errors="coerce"
        ),
    })
    n_raw = len(df)
    df = df.dropna()
    df["Date"] = df["Date"].dt.normalize()
    df = df.groupby("Date", as_index=False)["PM2.5"].mean().sort_values("Date")
    if df.empty:
        raise DataError("Aucune ligne valide (Date + PM2.5) n'a été trouvée.")
    df.attrs["dropped"] = n_raw - len(df)
    return df.reset_index(drop=True)


def load_master() -> pd.DataFrame | None:
    if not config.MASTER_CSV.exists():
        return None
    df = pd.read_csv(config.MASTER_CSV, parse_dates=["Date"])
    return df.sort_values("Date").reset_index(drop=True)


def save_master(df: pd.DataFrame) -> None:
    df.to_csv(config.MASTER_CSV, index=False)


def merge_into_master(new: pd.DataFrame, mode: str = "merge") -> tuple[pd.DataFrame, dict]:
    """mode='merge' : ajoute/actualise les dates ; 'replace' : remplace tout."""
    old = load_master() if mode == "merge" else None
    n_before = 0 if old is None else len(old)
    if old is not None:
        combined = pd.concat([old, new]).drop_duplicates("Date", keep="last")
    else:
        combined = new
    combined = combined.sort_values("Date").reset_index(drop=True)
    save_master(combined)
    return combined, {"rows_before": n_before, "rows_after": len(combined),
                      "rows_added": max(len(combined) - n_before, 0)}


def summary(df: pd.DataFrame | None) -> dict:
    if df is None or df.empty:
        return {"available": False}
    full = pd.date_range(df["Date"].min(), df["Date"].max(), freq="D")
    return {
        "available": True,
        "rows": int(len(df)),
        "start": df["Date"].min().strftime("%Y-%m-%d"),
        "end": df["Date"].max().strftime("%Y-%m-%d"),
        "min": round(float(df["PM2.5"].min()), 2),
        "max": round(float(df["PM2.5"].max()), 2),
        "mean": round(float(df["PM2.5"].mean()), 2),
        "missing_days": int(len(full) - len(df)),
        "enough_to_train": bool(len(df) >= config.MIN_ROWS),
        "min_rows": config.MIN_ROWS,
    }


def history_records(df: pd.DataFrame | None, last_n: int = 120) -> list[dict]:
    if df is None:
        return []
    tail = df.tail(last_n)
    return [{"Date": d.strftime("%Y-%m-%d"), "PM25": round(float(v), 2)}
            for d, v in zip(tail["Date"], tail["PM2.5"])]


def make_demo_data(days: int = 540) -> pd.DataFrame:
    """Série SYNTHÉTIQUE (démonstration uniquement) : saison sèche/harmattan + bruit."""
    rng = np.random.default_rng(config.SEED)
    end = pd.Timestamp(datetime.now().date()) - pd.Timedelta(days=1)
    dates = pd.date_range(end=end, periods=days, freq="D")
    doy = dates.dayofyear.to_numpy()
    season = 35 + 25 * np.cos(2 * np.pi * (doy - 20) / 365)  # pic en saison sèche
    noise = np.zeros(days)
    for i in range(1, days):  # AR(1)
        noise[i] = 0.75 * noise[i - 1] + rng.normal(0, 9)
    spikes = (rng.random(days) < 0.03) * rng.uniform(20, 60, days)
    pm = np.clip(season + noise + spikes, 5, None)
    return pd.DataFrame({"Date": dates, "PM2.5": pm.round(1)})


def template_xlsx() -> bytes:
    df = pd.DataFrame({
        "Date": pd.date_range("2026-01-01", periods=3, freq="D"),
        "PM2.5": [32.5, 41.2, 38.0],
    })
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df.to_excel(w, index=False, sheet_name="PM2_5")
    return buf.getvalue()
