# Patrones agénticos aplicados en este proyecto

Documento de referencia sobre los conceptos de arquitectura agéntica que
aparecen en `nfip_agent.py` y `nfip_genai_narrative.py`, con la
implementación concreta de cada uno y las decisiones de diseño detrás.

El objetivo es doble: dejar registro de por qué el agente está construido
así, y servir de material de referencia sobre patrones que son
independientes del proveedor de modelo.

---

## Índice

1. [Tool calling](#1--tool-calling-uso-de-herramientas)
2. [Harness](#2--harness)
3. [Ventana de contexto](#3--ventana-de-contexto)
4. [Planificación](#4--planificación)
5. [Trazabilidad y evaluación](#5--trazabilidad-y-evaluación)
6. [Diseño de prompt como mecanismo de control](#6--diseño-de-prompt-como-mecanismo-de-control)
7. [Límites de seguridad](#7--límites-de-seguridad)
8. [Separación de configuración y lógica](#8--separación-de-configuración-y-lógica)
9. [Patrones no implementados y por qué](#9--patrones-no-implementados-y-por-qué)
10. [Sobre la agnosticidad al proveedor](#10--sobre-la-agnosticidad-al-proveedor)

---

## 1 — Tool calling (uso de herramientas)

### Qué es

El modelo de lenguaje no ejecuta código. Lo que hace es **decidir** qué
función conviene llamar y con qué parámetros, y devolver esa decisión en
formato estructurado. El código de la aplicación ejecuta la función real y
le devuelve el resultado.

La distinción es importante: el modelo tiene capacidad de decisión, no de
ejecución. Todo lo que efectivamente ocurre lo hace código determinista.

### Cómo se aplica acá

Se definen dos herramientas con su esquema JSON:

```python
tools = [
    {
        "name": "consultar_trimestre",
        "description": "Devuelve los datos de forecast ... de un trimestre específico.",
        "input_schema": { ... }
    },
    {
        "name": "filtrar_trimestres_riesgo",
        "description": "Devuelve la lista de trimestres cuya probabilidad ... supera un umbral.",
        "input_schema": { ... }
    }
]
```

Detrás de cada una hay una función de pandas normal, sin ninguna
dependencia de IA:

```python
def filtrar_trimestres_riesgo(umbral: float) -> list:
    filtrado = df[df["prob_evento_catastrofico"] > umbral]
    return filtrado[["quarter", "prob_evento_catastrofico"]].to_dict("records")
```

### Decisión de diseño: el modelo no calcula

**Todos los números salen del código, ninguno del modelo.** El modelo elige
qué consultar y redacta la respuesta; los valores provienen del CSV a
través de pandas.

Esto acota el modo de fallo posible. Si el modelo se equivoca, se equivoca
eligiendo qué preguntar — un error visible y verificable en el log. No
puede inventar una cifra, porque nunca produce cifras.

Es una diferencia sustancial frente a pasarle los datos en el prompt y
pedirle que calcule: en ese caso, un error de aritmética es indistinguible
de un resultado correcto para quien lee la respuesta.

### La descripción de la herramienta es parte del diseño

El modelo decide en base a lo que dice la descripción. Si es incompleta,
decide mal.

Caso concreto observado en este proyecto: la descripción original del
parámetro `umbral` decía únicamente *"valor entre 0.0 y 1.0"*. El log
mostró que el agente tanteaba a ciegas — probaba 0.5, no obtenía
resultados, bajaba a 0.3, después a 0.2 — gastando llamadas a la API en
adivinar el rango.

La corrección fue declarar el rango real de los datos en la descripción:

> *"Umbral de probabilidad entre 0.0 y 1.0. En el forecast actual las
> probabilidades observadas van de 0.0 a 0.312, así que umbrales por
> encima de 0.32 no devuelven resultados."*

**Principio general:** todo supuesto no obvio sobre los datos tiene que
viajar dentro de la descripción de la herramienta que los expone. El agente
solo sabe lo que se le declara ahí.

Corolario para este proyecto: si en el futuro se expusiera `avg_severity`
como herramienta, su descripción tendría que aclarar que el 22.3% de los
reclamos tiene pago cero (ver README, sección de validación), o el agente
reportaría un promedio diluido sin advertirlo.

---

## 2 — Harness

### Qué es

Toda la infraestructura que rodea al modelo para convertirlo en una
aplicación. El modelo, por sí solo, recibe texto y devuelve texto: no tiene
memoria, no ejecuta nada, no itera.

El harness es lo que hace posible todo lo demás: el loop, el manejo de
errores, el ensamblado de mensajes, la extracción de contenido, los cortes
de seguridad.

### Cómo se aplica acá

El harness de este proyecto está escrito a mano, sin framework:

```python
for vuelta in range(max_vueltas):
    response = client.messages.create(...)

    if response.stop_reason != "tool_use":
        return next(b.text for b in response.content if b.type == "text")

    messages.append({"role": "assistant", "content": response.content})
    tool_results = []
    for block in response.content:
        if block.type == "tool_use":
            result = ejecutar_herramienta(block.name, block.input)
            loggear_vuelta(...)
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": json.dumps(result),
            })
    messages.append({"role": "user", "content": tool_results})
```

Piezas del harness visibles acá:

| Elemento | Función |
|---|---|
| `stop_reason` | Determina si el modelo pidió una herramienta o ya tiene respuesta final |
| `tool_use_id` | Vincula cada resultado con el pedido que lo originó (necesario cuando pide varias herramientas en una vuelta) |
| Filtrado por `b.type == "text"` | La respuesta puede traer bloques de razonamiento además de texto; asumir que el primero es texto es frágil |
| `messages.append()` | Construye el historial que se reenvía en cada vuelta |

### Decisión de diseño: sin framework

Se evaluaron frameworks de agentes (Hermes, AutoGen) y se descartaron para
este caso de uso. El razonamiento: para consultas estructuradas sobre un
dataset acotado, la autonomía que ofrecen esos frameworks excede lo
necesario y agrega una capa de abstracción que dificulta entender y
auditar el comportamiento.

Escribir el harness a mano tiene un costo — más código propio que mantener —
pero permite saber exactamente qué ocurre en cada paso. Para un proyecto
cuyo objetivo incluye poder explicar y auditar sus decisiones, esa
transparencia pesa más que la velocidad de desarrollo.

### Un bug ilustrativo

Durante el desarrollo, el bloque de ejecución de herramientas quedó
accidentalmente fuera del `for` por un error de indentación. El resultado:
el agente daba las cinco vueltas llamando a la API sin ejecutar ninguna
herramienta ni acumular mensajes — reenviando la misma pregunta cinco veces
y agotando el límite.

El síntoma visible era idéntico al de un problema de diseño de prompt. Solo
instrumentando el loop (imprimiendo `stop_reason` en cada vuelta) se
distinguió que el modelo **sí** estaba pidiendo herramientas y el harness
no las procesaba.

**Lección:** en un agente, un fallo del harness y un fallo de razonamiento
del modelo se ven igual desde afuera. Sin instrumentación no se distinguen.

---

## 3 — Ventana de contexto

### Qué es

Todo lo que el modelo "ve" en una llamada: el prompt, el historial, las
definiciones de herramientas y los resultados devueltos. Tiene un límite de
tamaño, y es también todo lo que el modelo sabe en ese momento — no
recuerda llamadas anteriores salvo que se le reenvíen.

### Cómo se aplica acá

El modelo no tiene memoria entre llamadas. La continuidad la construye el
código acumulando mensajes:

```
[pregunta del usuario]
→ [modelo: "quiero filtrar_trimestres_riesgo con umbral=0.25"]
→ [resultado de esa función]
→ [modelo: "ahora quiero consultar_trimestre para estos dos"]
→ [resultados]
→ [modelo: respuesta final en texto]
```

Cada vuelta agranda la ventana. Por eso el límite de vueltas tiene también
una función práctica además de la de seguridad: contiene el crecimiento del
contexto.

`max_tokens` controla el otro extremo: cuánto puede generar el modelo por
respuesta. En este proyecto se centralizó en `config.py`
(`MAX_TOKENS_NARRATIVA = 900`, `MAX_TOKENS_AGENTE = 1024`) después de un
episodio de truncamiento en la capa de narrativa.

---

## 4 — Planificación

### Qué es

Que el modelo descomponga una tarea en pasos y decida el siguiente según lo
que obtuvo del anterior, sin que la secuencia esté programada.

### Cómo se aplica acá

Comportamiento observado ante la pregunta *"¿cuáles son los trimestres de
mayor riesgo?"*, tomado del log real:

```
vuelta 1 → filtrar_trimestres_riesgo(umbral=0.25)
           → devuelve 2026-07-01 y 2027-07-01
vuelta 2 → consultar_trimestre('2026-07-01')
           consultar_trimestre('2027-07-01')
           → devuelve cuantiles de ambos
respuesta final: compara mediana, P90 y P99 de los dos trimestres
```

Nadie programó esa secuencia. El modelo determinó que necesitaba primero
identificar los trimestres relevantes y después obtener su detalle, y
encadenó las llamadas en consecuencia. Las dos consultas de la vuelta 2 se
pidieron en paralelo dentro de la misma respuesta.

### Límite observado

La planificación depende de que las herramientas disponibles permitan
responder la pregunta. Ante *"¿cuál fue el peor trimestre?"* — donde "peor"
es ambiguo entre probabilidad y severidad, y ninguna herramienta ordena por
severidad — el agente agotó vueltas tanteando y terminó pidiendo
aclaración al usuario.

Ese comportamiento es correcto (preguntar en vez de inventar un criterio),
pero señala una brecha de diseño: falta una herramienta que responda
directamente esa pregunta.

---

## 5 — Trazabilidad y evaluación

### Qué es

Registrar de forma persistente qué hizo el agente en cada paso. Es
prerrequisito de cualquier evaluación sistemática: sin registro no hay nada
que medir.

### Cómo se aplica acá

Cada vuelta del loop se persiste en `agent_log.jsonl`:

```python
def loggear_vuelta(pregunta, vuelta, herramienta, tool_input, resultado):
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
```

### Por qué JSONL y no JSON

Cada línea es un objeto JSON independiente. Eso permite agregar registros
sin reescribir el archivo completo (modo `"a"`, append) y leerlo de forma
incremental aunque crezca. Con un JSON convencional habría que cargar todo
el contenido, insertar el registro y volver a escribirlo entero en cada
llamada.

### Para qué sirve

**Depuración.** Sin log, un comportamiento anómalo solo deja la respuesta
final como evidencia. Con log, se reconstruye la secuencia completa de
decisiones.

**Detección de ineficiencia.** El log reveló que el agente llamaba dos
veces a `filtrar_trimestres_riesgo` con umbrales distintos obteniendo el
mismo resultado — una llamada desperdiciada por corrida, invisible en la
salida de consola.

**Construcción de un dataset de evaluación.** Cada corrida deja registro de
la pregunta y el comportamiento. Acumuladas, permiten medir: ¿elige la
herramienta correcta? ¿cuántas vueltas necesita en promedio? ¿en qué tipo
de pregunta se pierde?

### Conexión con agentes de escritura

En un agente de solo lectura como este, el log es una herramienta de
depuración. En un agente con permisos de escritura — que cree registros,
envíe mensajes o modifique sistemas — pasa a ser un requisito de
gobernanza: sin él no hay forma de reconstruir qué se hizo ni con qué
justificación.

Vale notar que escribir a un archivo es, en sí mismo, la versión más simple
y contenida del patrón de escritura: una operación con efecto persistente,
acotada y auditable.

---

## 6 — Diseño de prompt como mecanismo de control

### Qué es

Usar las instrucciones del prompt para acotar el comportamiento del modelo,
en lugar de depender de parámetros de muestreo.

### Cómo se aplica acá

En la capa de narrativa (`nfip_genai_narrative.py`), el parámetro
`temperature` no se usa — está deprecado en la generación actual de modelos
Claude. El control de precisión recae enteramente en el prompt, con
restricciones derivadas de errores observados en corridas reales:

- No inventar causas de los eventos catastróficos.
- No afirmar certeza sobre eventos futuros específicos.
- Explicar "mediana" y "P99" en su primera aparición.
- Evitar la palabra "razón" en sentido matemático, por su ambigüedad con
  "motivo" en español.

Cada una de esas reglas se agregó después de leer una salida concreta que
la motivaba, no de forma preventiva.

### Verificación

El efecto es observable en la salida generada. Un fragmento de la última
corrida:

> *"No estamos proyectando que un evento catastrófico específico vaya a
> ocurrir. Estamos señalando que, durante los trimestres de julio, existe
> una probabilidad no despreciable..."*

La distinción entre probabilidad y predicción aparece explícitamente, que
es exactamente lo que la restricción buscaba.

---

## 7 — Límites de seguridad

### Qué es

Cortes duros que garantizan terminación y acotan el costo, independientes
de lo que decida el modelo.

### Cómo se aplica acá

```python
def preguntar_al_agente(pregunta_usuario, max_vueltas=MAX_VUELTAS_AGENTE):
    for vuelta in range(max_vueltas):
        ...
    return f"[Se alcanzó el límite de {max_vueltas} vueltas sin llegar a una respuesta final]"
```

Dos propiedades del diseño:

**Termina siempre.** Un modelo puede quedarse pidiendo herramientas
indefinidamente. El `range()` garantiza que el loop termina pase lo que
pase.

**Falla visiblemente.** Al agotarse el límite, devuelve un mensaje
explícito en vez de una respuesta vacía o un error críptico. Quien lo usa
sabe que algo no funcionó.

### Mejora pendiente

Actualmente, al agotar el límite se pierde todo lo que el agente venía
elaborando. Una mejora sería devolver el último contenido de texto
producido junto con la advertencia, en lugar de descartarlo.

---

## 8 — Separación de configuración y lógica

### Qué es

Los valores que cambian con frecuencia (modelo, límites, umbrales) viven en
un archivo aparte del código que los usa.

### Cómo se aplica acá

`config.py`:

```python
CLAUDE_MODEL = "claude-sonnet-5"
MAX_TOKENS_NARRATIVA = 900
MAX_TOKENS_AGENTE = 1024
MAX_VUELTAS_AGENTE = 5
```

Antes de este cambio, el nombre del modelo estaba escrito en dos archivos
distintos.

### Por qué importa en un proyecto con IA

**Consistencia.** Con el valor duplicado, actualizar uno y olvidar el otro
hace que dos componentes corran con modelos distintos sin ningún error
visible. Los resultados dejan de ser comparables en silencio.

**Experimentación de costo.** Probar un modelo más barato para una tarea
simple (como la narrativa) pasa a ser cambiar una línea, en vez de editar
varios archivos.

Este proyecto ya tuvo un incidente del tipo que este patrón previene: en un
proyecto hermano, dos archivos tenían versiones distintas de la misma
función de esquema, y el agente reportaba correctamente la ausencia de
reglas de negocio que sí existían — en el otro archivo.

---

## 9 — Patrones no implementados y por qué

Enumerarlos importa tanto como los aplicados: saber qué falta es parte de
conocer el alcance real de lo construido.

### Reflexión

**Qué sería:** una segunda pasada donde el agente critica su propia
respuesta antes de entregarla.

**Por qué no está:** el diseño actual acota los errores posibles al
*qué consultar*, no al contenido de los números. Una capa de reflexión
duplicaría el costo por consulta con beneficio marginal en este caso de uso.

**Cuándo tendría sentido:** si el agente redactara conclusiones o
recomendaciones en lugar de reportar valores consultados.

### Memoria conversacional

**Qué sería:** que el agente recuerde preguntas anteriores dentro de una
sesión, para poder resolver referencias como "y el trimestre anterior".

**Por qué no está:** este agente responde una pregunta por ejecución. En un
proyecto hermano sí está implementado, moviendo la lista de mensajes fuera
del loop de preguntas.

### Prompt caching

**Qué sería:** que el proveedor guarde procesado el bloque inicial que se
repite entre llamadas, reduciendo costo y latencia.

**Por qué no está:** aplicable pero no implementado. Las definiciones de
herramientas se reenvían idénticas en cada vuelta, así que hay margen real
de mejora.

### Colaboración multi-agente

**Qué sería:** varios agentes con roles distintos coordinándose.

**Por qué no está:** el caso de uso no lo justifica. Consultar un forecast
de ocho filas no requiere división de trabajo.

### Herramientas de escritura

**Qué sería:** que el agente pueda modificar sistemas, no solo leerlos.

**Por qué no está:** la arquitectura del loop sería idéntica — cambia solo
qué hace la función ejecutada. Lo que cambia sustancialmente es todo lo
demás: permisos acotados, confirmación humana en acciones irreversibles,
idempotencia, rollback y auditoría. Esa capa de gobernanza es la mayor
parte del trabajo real, y no es diseño de prompts sino ingeniería de
sistemas.

---

## 10 — Sobre la agnosticidad al proveedor

El código de este proyecto usa la API de Anthropic. Los patrones descritos
acá no dependen de ella.

El loop de tool use, el manejo del estado de parada, la acumulación de
mensajes, la vinculación de resultados con pedidos y los límites de
seguridad son conceptualmente equivalentes en cualquier proveedor que
soporte tool calling. Lo que cambia es la sintaxis del SDK y los nombres de
los campos.

Un ejercicio de abstracción explícita aparece en un proyecto hermano, donde
la llamada al modelo se encapsuló en clases intercambiables (`ClaudeLLM` /
`MockLLM`) para permitir desarrollar y probar herramientas sin consumir
API. Ese es el primer paso hacia código independiente del proveedor: aislar
la llamada detrás de una interfaz propia.

Dado el ritmo de cambio de las herramientas de esta capa, invertir en
entender los patrones rinde más que especializarse en un SDK concreto.