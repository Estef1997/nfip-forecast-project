"""
Paso 1 (v3): Descarga el archivo COMPLETO de reclamos NFIP directo desde
FEMA, en vez de paginar por la API con $skip.

Por qué el cambio de estrategia: paginar a través de casi 3 millones de
filas con $skip satura el servidor de FEMA a medida que el offset crece
-- por eso los 503 "Service Unavailable" que veías, incluso con
reintentos. FEMA mismo recomienda, para análisis histórico completo,
descargar el archivo completo en vez de paginar por la API. Este script
hace eso: una sola descarga, sin fragilidad de paginación.
"""

import os

import pandas as pd
import requests

DOWNLOAD_URL = "https://www.fema.gov/about/reports-and-data/openfema/FimaNfipClaims.parquet"
RAW_FILE = "nfip_claims_raw.parquet"

# Campos mínimos para frecuencia + severidad a nivel nacional/trimestre.
FIELDS = [
    "dateOfLoss",
    "state",
    "amountPaidOnBuildingClaim",
    "amountPaidOnContentsClaim",
    "amountPaidOnIncreasedCostOfComplianceClaim",
]


def download_full_file():
    """Descarga el archivo completo una sola vez. Si ya existe, no lo
    vuelve a bajar (para no perder tiempo si corrés el script de nuevo)."""
    if os.path.exists(RAW_FILE):
        print(f"{RAW_FILE} ya existe, no vuelvo a descargar.")
        return

    print(f"Descargando dataset completo desde:\n  {DOWNLOAD_URL}")
    with requests.get(DOWNLOAD_URL, stream=True, timeout=600) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("content-length", 0))
        downloaded = 0
        with open(RAW_FILE, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                f.write(chunk)
                downloaded += len(chunk)
                if total:
                    pct = downloaded / total * 100
                    print(f"\r  {downloaded / 1e6:.0f} MB / {total / 1e6:.0f} MB "
                          f"({pct:.1f}%)", end="")
    print("\nDescarga completa.")


def to_quarterly_frequency_severity(df):
    """Colapsa el detalle de reclamos a series trimestrales nacionales."""
    df["dateOfLoss"] = pd.to_datetime(df["dateOfLoss"])
    df["quarter"] = df["dateOfLoss"].dt.to_period("Q")

    df["total_paid"] = (
        df["amountPaidOnBuildingClaim"].fillna(0)
        + df["amountPaidOnContentsClaim"].fillna(0)
        + df["amountPaidOnIncreasedCostOfComplianceClaim"].fillna(0)
    )

    agg = df.groupby("quarter").agg(
        n_claims=("total_paid", "count"),      # frecuencia
        avg_severity=("total_paid", "mean"),    # severidad promedio
        total_paid=("total_paid", "sum"),       # pérdida agregada
    )
    return agg


if __name__ == "__main__":
    download_full_file()

    print("Leyendo solo las columnas necesarias del parquet...")
    df = pd.read_parquet(RAW_FILE, columns=FIELDS)
    print(df.shape)
    print(df.head())

    quarterly = to_quarterly_frequency_severity(df)
    print(quarterly)

    quarterly.to_csv("nfip_quarterly_frequency_severity.csv")
    print("Guardado: nfip_quarterly_frequency_severity.csv")