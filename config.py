"""Configuración centralizada del proyecto."""

# Modelo de Claude usado por la capa de narrativa y por el agente.
# Cambiar acá se propaga a todos los scripts.
CLAUDE_MODEL = "claude-sonnet-5"

# Límite de tokens para la narrativa ejecutiva
MAX_TOKENS_NARRATIVA = 900

# Límite de tokens para cada respuesta del agente
MAX_TOKENS_AGENTE = 1024

# Máximo de vueltas del loop del agente antes de cortar
MAX_VUELTAS_AGENTE = 5