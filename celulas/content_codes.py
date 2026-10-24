"""
Catálogo de Códigos de Contenido de la calculadora ADS.

Toda solicitud y toda respuesta que circula por el Campo de Datos lleva uno de
estos códigos. El código identifica el servicio Y el tipo de mensaje:
    <SERVICIO>_REQ  -> solicitud de una operación
    <SERVICIO>_RES  -> respuesta a esa operación

Para agregar un servicio nuevo basta con añadirlo en SERVICIOS (y su función
en asm_calculadora.py); ni el nodo ni el ACP necesitan cambios.
"""

SUM_REQ, SUM_RES = "SUM_REQ", "SUM_RES"   # Suma
SUB_REQ, SUB_RES = "SUB_REQ", "SUB_RES"   # Resta
MUL_REQ, MUL_RES = "MUL_REQ", "MUL_RES"   # Multiplicación
DIV_REQ, DIV_RES = "DIV_REQ", "DIV_RES"   # División

# servicio -> (código solicitud, código respuesta, símbolo, nombre)
SERVICIOS = {
    "SUM": (SUM_REQ, SUM_RES, "+", "Suma"),
    "SUB": (SUB_REQ, SUB_RES, "-", "Resta"),
    "MUL": (MUL_REQ, MUL_RES, "×", "Multiplicación"),
    "DIV": (DIV_REQ, DIV_RES, "÷", "División"),
}

# Alias aceptados en la línea de comandos: --servicio suma, +, SUM...
ALIAS = {
    "SUM": "SUM", "SUMA": "SUM", "+": "SUM",
    "SUB": "SUB", "RESTA": "SUB", "-": "SUB",
    "MUL": "MUL", "MULTIPLICACION": "MUL", "MULTIPLICACIÓN": "MUL", "X": "MUL", "*": "MUL",
    "DIV": "DIV", "DIVISION": "DIV", "DIVISIÓN": "DIV", "/": "DIV",
}

SOLICITUDES = {req for req, _, _, _ in SERVICIOS.values()}
RESPUESTAS = {res for _, res, _, _ in SERVICIOS.values()}
TODOS = SOLICITUDES | RESPUESTAS


def codigo_solicitud(servicio):
    return SERVICIOS[servicio][0]


def codigo_respuesta(servicio):
    return SERVICIOS[servicio][1]


def servicio_de(codigo):
    """'SUM_REQ' o 'SUM_RES' -> 'SUM' (None si el código no es del catálogo)."""
    for servicio, (req, res, _, _) in SERVICIOS.items():
        if codigo in (req, res):
            return servicio
    return None


def es_solicitud(codigo):
    return codigo in SOLICITUDES


def es_respuesta(codigo):
    return codigo in RESPUESTAS


def normalizar_servicio(texto):
    servicio = ALIAS.get(str(texto).strip().upper())
    if servicio is None:
        raise ValueError(f"servicio desconocido: {texto!r} (usa SUM, SUB, MUL o DIV)")
    return servicio
