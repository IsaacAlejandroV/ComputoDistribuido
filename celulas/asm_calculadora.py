"""
ASM (Application Software Module) de la calculadora.

Contiene únicamente la lógica de negocio: las cuatro operaciones. No sabe nada
de sockets, nodos ni broadcast; eso es trabajo del ACP.
"""
import math


class ErrorOperacion(Exception):
    """Error de negocio (p. ej. división entre cero) que se devuelve en la respuesta."""


def _numero(valor):
    if isinstance(valor, bool) or not isinstance(valor, (int, float)) or not math.isfinite(valor):
        raise ErrorOperacion(f"operando inválido: {valor!r}")
    return valor


def _limpiar(resultado):
    """Devuelve enteros cuando el resultado es exacto (6.0 -> 6) y evita ruido de punto flotante."""
    if isinstance(resultado, float):
        if not math.isfinite(resultado):
            raise ErrorOperacion("resultado fuera de rango")
        resultado = round(resultado, 10)
        if resultado.is_integer() and abs(resultado) < 1e15:
            return int(resultado)
    return resultado


OPERACIONES = {
    "SUM": lambda a, b: a + b,
    "SUB": lambda a, b: a - b,
    "MUL": lambda a, b: a * b,
    "DIV": lambda a, b: a / b,
}


def calcular(servicio, operandos):
    """Ejecuta la operación del servicio sobre [a, b]. Lanza ErrorOperacion si no es posible."""
    if servicio not in OPERACIONES:
        raise ErrorOperacion(f"servicio no soportado: {servicio}")
    if not isinstance(operandos, list) or len(operandos) != 2:
        raise ErrorOperacion("se requieren exactamente dos operandos")
    a, b = (_numero(x) for x in operandos)
    if servicio == "DIV" and b == 0:
        raise ErrorOperacion("división entre cero")
    try:
        return _limpiar(OPERACIONES[servicio](a, b))
    except OverflowError:
        raise ErrorOperacion("resultado fuera de rango")
