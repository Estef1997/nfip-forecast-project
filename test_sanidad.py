"""Tests de sanidad sobre los resultados del forecast NFIP."""

import pandas as pd

FORECAST_FILE = "nfip_final_combined_forecast.csv"


def test_orden_de_cuantiles():
    """Los cuantiles deben respetar el orden matemático obvio."""
    df = pd.read_csv(FORECAST_FILE)
    for _, fila in df.iterrows():
        q = fila["quarter"]
        assert fila["loss_p10_M"] <= fila["loss_mediana_M"], f"P10 > mediana en {q}"
        assert fila["loss_mediana_M"] <= fila["loss_p90_M"], f"Mediana > P90 en {q}"
        assert fila["loss_p90_M"] <= fila["loss_p99_M"], f"P90 > P99 en {q}"
    print(f"OK: orden de cuantiles correcto en {len(df)} trimestres")


def test_valores_no_negativos():
    """Las pérdidas no pueden ser negativas."""
    df = pd.read_csv(FORECAST_FILE)
    for col in ["loss_p10_M", "loss_mediana_M", "loss_p90_M", "loss_p99_M"]:
        assert (df[col] >= 0).all(), f"Valores negativos en {col}"
    print("OK: todos los cuantiles son no negativos")


def test_probabilidad_en_rango():
    """La probabilidad catastrófica debe estar entre 0 y 1."""
    df = pd.read_csv(FORECAST_FILE)
    col = "prob_evento_catastrofico"
    assert (df[col] >= 0).all() and (df[col] <= 1).all(), f"Probabilidades fuera de [0,1] en {col}"
    print("OK: probabilidades dentro de rango")


def test_sin_nulos():
    """Ninguna celda del forecast debe quedar vacía."""
    df = pd.read_csv(FORECAST_FILE)
    assert not df.isnull().any().any(), "Hay valores nulos en el forecast"
    print("OK: sin valores nulos")


if __name__ == "__main__":
    test_orden_de_cuantiles()
    test_valores_no_negativos()
    test_probabilidad_en_rango()
    test_sin_nulos()
    print("\nTodos los tests pasaron.")