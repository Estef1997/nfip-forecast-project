"""
Paso 2: Ajustar la severidad de reclamos por inflación (CPI-U), para
poder comparar dólares de 1978 contra dólares de 2025 de forma justa.

Fuente del índice: CPI-U anual promedio, Federal Reserve Bank of
Minneapolis / BLS (base 1982-1984=100).
"""

import pandas as pd
import matplotlib.pyplot as plt

INPUT_FILE = "nfip_quarterly_frequency_severity.csv"
OUTPUT_FILE = "nfip_quarterly_adjusted.csv"
BASE_YEAR = 2025  # expresamos todo en dólares de este año

CPI = {
    1978: 65.2, 1979: 72.6, 1980: 82.4, 1981: 90.9, 1982: 96.5, 1983: 99.6,
    1984: 103.9, 1985: 107.6, 1986: 109.6, 1987: 113.6, 1988: 118.3, 1989: 124.0,
    1990: 130.7, 1991: 136.2, 1992: 140.3, 1993: 144.5, 1994: 148.2, 1995: 152.4,
    1996: 156.9, 1997: 160.5, 1998: 163.0, 1999: 166.6, 2000: 172.2, 2001: 177.1,
    2002: 179.9, 2003: 184.0, 2004: 188.9, 2005: 195.3, 2006: 201.6, 2007: 207.3,
    2008: 215.3, 2009: 214.5, 2010: 218.1, 2011: 224.9, 2012: 229.6, 2013: 233.0,
    2014: 236.7, 2015: 237.0, 2016: 240.0, 2017: 245.1, 2018: 251.1, 2019: 255.7,
    2020: 258.8, 2021: 271.0, 2022: 292.7, 2023: 304.7, 2024: 313.7, 2025: 321.9,
    2026: 330.9,  # estimado, primeros meses del año
}


def adjust_for_inflation():
    df = pd.read_csv(INPUT_FILE)
    df["year"] = df["quarter"].str[:4].astype(int)
    df["quarter_dt"] = pd.PeriodIndex(df["quarter"], freq="Q").to_timestamp()

    base_cpi = CPI[BASE_YEAR]
    df["deflator"] = base_cpi / df["year"].map(CPI)

    df["avg_severity_real"] = df["avg_severity"] * df["deflator"]
    df["total_paid_real"] = df["total_paid"] * df["deflator"]

    df.to_csv(OUTPUT_FILE, index=False)
    print(f"Guardado: {OUTPUT_FILE}")
    return df


def plot_comparison(df):
    fig, ax = plt.subplots(figsize=(13, 5))
    ax.plot(df["quarter_dt"], df["avg_severity"],
            label="Severidad promedio (nominal)", color="#D85A30", linewidth=1.2)
    ax.plot(df["quarter_dt"], df["avg_severity_real"],
            label=f"Severidad promedio (dólares constantes de {BASE_YEAR})",
            color="#378ADD", linewidth=1.4)
    ax.set_ylabel("USD por reclamo")
    ax.set_title("Severidad promedio por reclamo: nominal vs. ajustada por inflación")
    ax.legend()
    ax.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig("nfip_severity_real_vs_nominal.png", dpi=140)
    print("Gráfico guardado: nfip_severity_real_vs_nominal.png")


if __name__ == "__main__":
    df = adjust_for_inflation()
    plot_comparison(df)

    early = df[df["year"] == 1978]["avg_severity"].mean()
    late = df[df["year"] == 2025]["avg_severity"].mean()
    early_real = df[df["year"] == 1978]["avg_severity_real"].mean()
    late_real = df[df["year"] == 2025]["avg_severity_real"].mean()

    print(f"\nSeveridad promedio 1978 (nominal): ${early:,.0f}")
    print(f"Severidad promedio 2025 (nominal): ${late:,.0f}  -> {late/early:.1f}x")
    print(f"\nSeveridad promedio 1978 (dólares de {BASE_YEAR}): ${early_real:,.0f}")
    print(f"Severidad promedio 2025 (dólares de {BASE_YEAR}): ${late_real:,.0f}  -> {late_real/early_real:.1f}x")