
"""
Paso 8 (final): Narrativa ejecutiva automática con la API de Claude,
a partir del forecast combinado (frecuencia + severidad + EVT).

Nota: el parámetro `temperature` se sacó porque los modelos Claude más
nuevos ya no lo aceptan (deprecado) -- devuelve error 400 si se envía.
El control de precisión de la narrativa queda a cargo del diseño del
prompt (restricciones explícitas de no inventar causas, no afirmar
certeza, evitar lenguaje ambiguo, y explicar términos técnicos), no de
ese parámetro.
"""
from config import CLAUDE_MODEL, MAX_TOKENS_NARRATIVA, MAX_VUELTAS_AGENTE

import os
import anthropic
import pandas as pd

FORECAST_FILE = "nfip_final_combined_forecast.csv"


def build_prompt(df):
    rows_text = "\n".join(
        f"- {row.quarter[:10]}: prob. evento catastrófico {row.prob_evento_catastrofico*100:.1f}%, "
        f"mediana ${row.loss_mediana_M:,.0f}M, "
        f"P90 ${row.loss_p90_M:,.0f}M, P99 ${row.loss_p99_M:,.0f}M"
        for row in df.itertuples()
    )

    return f"""Sos un analista actuarial que resume forecasts de pérdidas del \
National Flood Insurance Program (NFIP) para un comité de riesgo y \
planificación de reservas/reinsurance. La audiencia son ejecutivos de alto \
rango, no necesariamente con formación técnica o estadística.

Estos son los datos del forecast de pérdida agregada trimestral (dólares \
reales de 2025), para los próximos 8 trimestres:

{rows_text}

Contexto que ya sabemos (no lo repitas como nuevo, usalo solo como marco): \
NO reportamos la media porque la cola de la distribución es tan pesada que \
la media matemática es inestable/indefinida -- por eso usamos mediana y \
percentiles (P90, P99) como medida de riesgo.

Escribí un resumen ejecutivo de no más de 280 palabras, en español, que:
1. Explicá "mediana" y "P99" la PRIMERA vez que aparezcan en el texto, \
   con una frase corta entre paréntesis -- por ejemplo: "la mediana \
   (el escenario más típico)" o "el P99 (el peor escenario dentro de \
   los considerados, superado solo 1 de cada 100 veces)". Esta \
   explicación es obligatoria, incluso si eso implica recortar detalle \
   en otras secciones.
2. Señale qué trimestre(s) concentran el mayor riesgo catastrófico y por qué \
   (según la probabilidad de evento catastrófico, no inventes causas).
3. Compare el P99 contra la mediana para mostrar la magnitud de la cola.
4. NO afirmes que un evento catastrófico específico va a ocurrir -- hablá \
   en términos de probabilidad y rango, no de certeza.
5. Tono: directo, para un comité de riesgo, sin adornos innecesarios.
6. Usá lenguaje claro y sin ambigüedad -- evitá la palabra "razón" para \
   referirte a una proporción o múltiplo (usá "múltiplo" o "esa brecha" \
   en su lugar, para no confundirla con "motivo/causa")."""


def generate_narrative():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("Configurá ANTHROPIC_API_KEY antes de correr esto.")

    df = pd.read_csv(FORECAST_FILE)
    prompt = build_prompt(df)

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model= CLAUDE_MODEL, max_tokens=MAX_TOKENS_NARRATIVA,
        messages=[{"role": "user", "content": prompt}],
    )
    # La respuesta puede traer varios bloques (thinking, text, tool_use).
    # Nos quedamos solo con los de texto y los unimos.
    partes = [b.text for b in response.content if b.type == "text"]
    return "\n".join(partes)


if __name__ == "__main__":
    narrative = generate_narrative()
    print("\n--- Resumen ejecutivo generado ---\n")
    print(narrative)
    with open("nfip_executive_summary.txt", "w", encoding="utf-8") as f:
        f.write(narrative)
    print("\nGuardado: nfip_executive_summary.txt")