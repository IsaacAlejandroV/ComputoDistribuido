"""
Registro en memoria de los últimos mensajes CONTENT que pasaron por este nodo.
Lo consume el panel gráfico a través de GET /content?since=N. El nodo no
interpreta el contenido: solo lo recuerda un rato para poder mostrarlo.
"""

import datetime
import json
import threading
import uuid
from collections import deque

MAX_EVENTOS = 200
MAX_DATO = 1000  # caracteres máximos que se guardan de un dato

BOOT = str(uuid.uuid4())  # cambia cada vez que el nodo arranca, para que el panel detecte reinicios
_lock = threading.Lock()
_eventos = deque(maxlen=MAX_EVENTOS)
_seq = 0


def _acotar(dato):
    try:
        texto = json.dumps(dato)
    except (TypeError, ValueError):
        texto = repr(dato)
    return dato if len(texto) <= MAX_DATO else texto[:MAX_DATO] + "…"


def registrar(origen, codigo, dato, msg_id, via=None):
    """`via` describe por qué conexión llegó (dict con node_id, role, address) o None si lo publicó este nodo."""
    global _seq
    evento = {
        "time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "node_id": origen, "content_code": codigo, "data": _acotar(dato),
        "msg_id": msg_id, "via": via,
    }
    with _lock:
        _seq += 1
        evento["seq"] = _seq
        _eventos.append(evento)


def desde(seq, limite=MAX_EVENTOS):
    with _lock:
        pendientes = [dict(e) for e in _eventos if e["seq"] > seq]
        return {"boot": BOOT, "last_seq": _seq, "events": pendientes[-limite:]}
