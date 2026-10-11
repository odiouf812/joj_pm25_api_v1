"""Fichiers téléchargeables : CSV, Excel (2 feuilles comme le notebook) et messages TXT."""
from __future__ import annotations

import io

import pandas as pd

FORECAST_COLS = ["Day", "Date", "Forecast", "SD", "Lower_95", "Upper_95",
                 "Class_Forecast", "Class_Lower_95", "Class_Upper_95"]


def forecast_df(results: dict) -> pd.DataFrame:
    df = pd.DataFrame(results["forecast"])[FORECAST_COLS]
    df["Date"] = pd.to_datetime(df["Date"])
    return df


def health_df(results: dict) -> pd.DataFrame:
    df = pd.DataFrame(results["health"])
    df["Date"] = pd.to_datetime(df["Date"])
    return df


def messages_df(results: dict) -> pd.DataFrame:
    df = pd.DataFrame(results["messages"])
    df["Date"] = pd.to_datetime(df["Date"])
    return df


def to_csv(results: dict) -> bytes:
    return forecast_df(results).to_csv(index=False).encode("utf-8-sig")


def to_xlsx(results: dict) -> bytes:
    from openpyxl.styles import Alignment, Font, PatternFill
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl", datetime_format="YYYY-MM-DD") as w:
        forecast_df(results).to_excel(w, sheet_name="Forecast_Classification", index=False)
        health_df(results).to_excel(w, sheet_name="Health_Indicators", index=False)
        messages_df(results).to_excel(w, sheet_name="Messages", index=False)
        for ws in w.book.worksheets:
            for c in ws[1]:
                c.font = Font(bold=True, color="FFFFFF")
                c.fill = PatternFill("solid", fgColor="0B3D91")
                c.alignment = Alignment(vertical="center")
            for col in ws.columns:
                width = max(len(str(c.value)) if c.value is not None else 0 for c in col)
                ws.column_dimensions[col[0].column_letter].width = min(max(width + 2, 10), 60)
            ws.freeze_panes = "A2"
    return buf.getvalue()


def messages_txt(results: dict) -> bytes:
    lines = ["JOJ DAKAR 2026 - MESSAGES SANITAIRES PM2,5", "=" * 60, ""]
    for m in results["messages"]:
        lines.append(f"[{m['Day']} - {m['Date']}]")
        lines.append(m["Message"] or
                     f"Pas de message : PM2,5 prévu <= {results['counterfactual']} µg/m³ "
                     "(valeur guide journalière de l’OMS).")
        lines.append("")
    return "\n".join(lines).encode("utf-8")
