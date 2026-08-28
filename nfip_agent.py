"""
nfip_agent.py -- Agente sobre el forecast NFIP.
Usa herramientas reales (consultar_trimestre, filtrar_trimestres_riesgo)
que Claude decide cuándo y cómo invocar, según la pregunta en lenguaje natural.
"""
from config import CLAUDE_MODEL, MAX_TOKENS_AGENTE, MAX_VUELTAS_AGENTE
from datetime import datetime
import anthropic
import pandas as pd
import json
import os

# --- Bloque 1: Datos y funciones reales ---

df = pd.read_csv("nfip_final_combined_forecast.csv")
df["quarter"] = df["quarter"].astype(str)


def consultar_trimestre(quarter: str) -> dict:
    """Devuelve los datos de forecast de un trimestre específico."""
    row = df[df["quarter"].str.startswith(quarter[:7])]
    if row.empty:
        return {"error": f"No hay datos para el trimestre {quarter}"}
    row = row.iloc[0]
    return {
        "quarter": row["quarter"],
        "prob_evento_catastrofico": float(row["prob_evento_catastrofico"]),
        "mediana_M": float(row["loss_mediana_M"]),
        "p90_M": float(row["loss_p90_M"]),
        "p99_M": float(row["loss_p99_M"]),
    }


def filtrar_trimestres_riesgo(umbral: float) -> list:
    """Devuelve los trimestres cuya probabilidad catastrófica supera el umbral dado (0.0 a 1.0)."""
    filtrado = df[df["prob_evento_catastrofico"] > umbral]
    return filtrado[["quarter", "prob_evento_catastrofico"]].to_dict("records")


# --- Bloque 2: Descripción de las herramientas para Claude ---

tools = [
    {
        "name": "consultar_trimestre",
        "description": "Devuelve los datos de forecast (probabilidad catastrófica, mediana, P90, P99) de un trimestre específico del NFIP.",
        "input_schema": {
            "type": "object",
            "properties": {
                "quarter": {
                    "type": "string",
                    "description": "Trimestre en formato YYYY-MM-DD, ej. '2026-07-01' para Q3 2026"
                }
            },
            "required": ["quarter"]
        }
    },
    {
        "name": "filtrar_trimestres_riesgo",
        "description": "Devuelve la lista de trimestres cuya probabilidad de evento catastrófico supera un umbral dado.",
        "input_schema": {
            "type": "object",
            "properties": {
                "umbral": {
                    "type": "number",
                    "description": "Umbral de probabilidad entre 0.0 y 1.0. En el forecast actual las probabilidades observadas van de 0.0 a 0.312, así que umbrales por encima de 0.32 no devuelven resultados."
                }
            },
            "required": ["umbral"]
        }
    }
]


# --- Bloque 3: Logging de las decisiones del agente ---

LOG_FILE = "agent_log.jsonl"


def loggear_vuelta(pregunta, vuelta, herramienta, tool_input, resultado):
    """Persiste una vuelta del loop del agente a un archivo JSONL.

    Cada línea es un objeto JSON independiente, así el archivo se puede
    leer incrementalmente y crece sin reescribirse.
    """
    registro = {
        "timestamp": datetime.now().isoformat(),
        "pregunta": pregunta,
        "vuelta": vuelta,
        "herramienta": herramienta,
        "input": tool_input,
        "resultado": str(resultado)[:500],
    }
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(registro, ensure_ascii=False) + "\n")


# --- Bloque 4: El loop del agente (con límite de seguridad) ---

def ejecutar_herramienta(name, tool_input):
    if name == "consultar_trimestre":
        return consultar_trimestre(tool_input["quarter"])
    elif name == "filtrar_trimestres_riesgo":
        return filtrar_trimestres_riesgo(tool_input["umbral"])


def preguntar_al_agente(pregunta_usuario, max_vueltas=MAX_VUELTAS_AGENTE):
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    messages = [{"role": "user", "content": pregunta_usuario}]

    for vuelta in range(max_vueltas):
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=MAX_TOKENS_AGENTE,
            tools=tools,
            messages=messages,
        )

        if response.stop_reason != "tool_use":
            return next(b.text for b in response.content if b.type == "text")

        messages.append({"role": "assistant", "content": response.content})
        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                print(f"  [Vuelta {vuelta+1}/{max_vueltas} -- Agente decidió usar: {block.name}({block.input})]")
                result = ejecutar_herramienta(block.name, block.input)
                loggear_vuelta(pregunta_usuario, vuelta + 1, block.name, block.input, result)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result),
                })
        messages.append({"role": "user", "content": tool_results})

    return f"[Se alcanzó el límite de {max_vueltas} vueltas sin llegar a una respuesta final -- revisá el diseño del prompt/herramientas]"


# --- Bloque 5: Probarlo ---

if __name__ == "__main__":
    pregunta = input("Preguntale algo al agente sobre el forecast NFIP: ")
    respuesta = preguntar_al_agente(pregunta)
    print("\n--- Respuesta del agente ---\n")
    print(respuesta)