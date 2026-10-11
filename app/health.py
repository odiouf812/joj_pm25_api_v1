"""Classification du PM2.5, RR / fraction attribuable et messages sanitaires."""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config

# Niveau -> (libellé court, couleur, texte officiel du notebook)
LEVELS = {
    1: ("Bon", "#00A651", "Aucune restriction majeure"),
    2: ("Acceptable", "#F4C20D", "Qualité acceptable pour la population générale"),
    3: ("Modéré", "#F77F00", "Risque modéré pour les personnes sensibles (asthme, enfants)."),
    4: ("Alerte", "#E31B23",
        "Alerte générale. Éviter les activités physiques intenses en extérieur."),
}
SCALE = [
    {"level": 1, "range": "≤ 15 µg/m³"},
    {"level": 2, "range": "15 – 40 µg/m³"},
    {"level": 3, "range": "40 – 65 µg/m³"},
    {"level": 4, "range": "> 65 µg/m³"},
]


def level_of(x) -> int | None:
    """Seuils continus (identiques au notebook)."""
    if x is None or pd.isna(x) or x <= 0:
        return None
    if x <= 15:
        return 1
    if x <= 40:
        return 2
    if x <= 65:
        return 3
    return 4


def classify_pm25(x) -> str | None:
    lv = level_of(x)
    return None if lv is None else LEVELS[lv][2]


def _class_block(x) -> dict:
    lv = level_of(x)
    if lv is None:
        return {"level": None, "label": "Non classé", "color": "#8A94A6", "text": None}
    return {"level": lv, "label": LEVELS[lv][0], "color": LEVELS[lv][1], "text": LEVELS[lv][2]}


def calc_rr_fa(forecast: float, rr_unit: float) -> dict:
    beta = np.log(rr_unit) / 10
    excess = max(forecast - config.COUNTERFACTUAL, 0)   # pas d'excès sous le contrefactuel
    rr_obs = float(np.exp(beta * excess))
    return {"RR_obs": rr_obs, "FA": (rr_obs - 1) / rr_obs}


def _fr(x: float, d: int = 2) -> str:
    return f"{x:.{d}f}".replace(".", ",")


def make_message(forecast: float, cv: dict, resp: dict) -> str:
    """Message unique (cardiovasculaire + respiratoire), émis si PM2,5 prévu > niveau de référence OMS."""
    ref = config.COUNTERFACTUAL
    x, y = 100 * (cv["RR_obs"] - 1), 100 * (resp["RR_obs"] - 1)
    return (
        f"PM2,5 prévu : {_fr(forecast, 1)} µg/m³. Cette concentration est supérieure à la valeur "
        f"guide journalière de l’OMS, fixée à {ref:d} µg/m³. Par rapport à ce niveau de référence, "
        f"le risque d’hospitalisation pour causes cardiovasculaires est estimé {_fr(x)} % plus élevé, "
        f"et celui pour causes respiratoires {_fr(y)} % plus élevé. La fraction attribuable est "
        f"estimée respectivement à {_fr(100 * cv['FA'])} % et {_fr(100 * resp['FA'])} %. Elle "
        f"représente, la part du risque d’hospitalisation estimé à cette "
        f"concentration qui est attribuable à l’exposition aux PM2,5 au-dessus du niveau de "
        f"référence de {ref:d} µg/m³."
    )


def build_results(fc: pd.DataFrame) -> dict:
    """Assemble prévisions + classification + indicateurs + messages (JSON-ready)."""
    fc = fc.copy()
    fc.insert(0, "Day", [f"J+{i + 1}" for i in range(len(fc))])

    forecasts = []
    for r in fc.itertuples():
        forecasts.append({
            "Day": r.Day, "Date": r.Date.strftime("%Y-%m-%d"),
            "Forecast": float(r.Forecast), "SD": float(r.SD),
            "Lower_95": float(r.Lower_95), "Upper_95": float(r.Upper_95),
            "Class_Forecast": classify_pm25(r.Forecast),
            "Class_Lower_95": classify_pm25(r.Lower_95),
            "Class_Upper_95": classify_pm25(r.Upper_95),
            "forecast_class": _class_block(r.Forecast),
            "lower_class": _class_block(r.Lower_95),
            "upper_class": _class_block(r.Upper_95),
        })

    health = []
    for r in fc.itertuples():
        for o in config.RR_TABLE:
            est = calc_rr_fa(r.Forecast, o["RR_unit"])
            lo = calc_rr_fa(r.Forecast, o["RR_low"])
            hi = calc_rr_fa(r.Forecast, o["RR_high"])
            health.append({
                "Day": r.Day, "Date": r.Date.strftime("%Y-%m-%d"),
                "Forecast": float(r.Forecast),
                "Outcome": o["Outcome"], "ICD10": o["ICD10"], "RR_unit": o["RR_unit"],
                "RR_obs": est["RR_obs"], "RR_obs_low": lo["RR_obs"], "RR_obs_high": hi["RR_obs"],
                "FA_pct": 100 * est["FA"], "FA_pct_low": 100 * lo["FA"],
                "FA_pct_high": 100 * hi["FA"],
            })
    messages = []
    for r in fc.itertuples():
        cv = calc_rr_fa(r.Forecast, config.RR_TABLE[0]["RR_unit"])
        rs = calc_rr_fa(r.Forecast, config.RR_TABLE[1]["RR_unit"])
        messages.append({
            "Day": r.Day, "Date": r.Date.strftime("%Y-%m-%d"), "Forecast": float(r.Forecast),
            "Message": make_message(r.Forecast, cv, rs) if r.Forecast > config.COUNTERFACTUAL else None,
        })
    return {"forecast": forecasts, "health": health, "messages": messages, "scale": SCALE,
            "levels": {k: {"label": v[0], "color": v[1], "text": v[2]} for k, v in LEVELS.items()},
            "counterfactual": config.COUNTERFACTUAL, "sn_reference": config.SN_REFERENCE}
