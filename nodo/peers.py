"""
Registro único de conexiones activas del nodo: incluye tanto los sockets
que este nodo abrió como CLIENTE (conectó hacia otro peer) como los que
aceptó como SERVIDOR (otro peer se conectó hacia él).

Es importante que el broadcast (enviar_mensaje_a_todos) recorra este
registro y no solo las conexiones salientes: si un nodo solo acepta
conexiones entrantes (por ejemplo, el nodo del profesor, al que todos los
equipos marcan), nunca podría enviar ACKs ni retransmitir (gossip) si el
broadcast ignorara esas conexiones entrantes.
"""

import threading
import datetime

conexiones = {}  # "ip:puerto" -> socket
_locks_envio = {}
_metadatos = {}
_lock = threading.RLock()

def registrar(direccion, conexion, tipo_conexion="desconocida"):
    with _lock:
        anterior = conexiones.get(direccion)
        conexiones[direccion] = conexion
        _locks_envio[direccion] = threading.Lock()
        _metadatos[direccion] = {
            "address": direccion,
            "connection": tipo_conexion.lower(),
            "role": "unknown",
            "node_id": None,
            "endpoint": None,
            "api_endpoint": None,
            "cell_type": None,
            "service": None,
            "connected_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
    if anterior is not None and anterior is not conexion:
        try:
            anterior.close()
        except OSError:
            pass

def eliminar(direccion, conexion=None):
    with _lock:
        actual = conexiones.get(direccion)
        if actual is None or (conexion is not None and actual is not conexion):
            return False
        conexiones.pop(direccion, None)
        _locks_envio.pop(direccion, None)
        _metadatos.pop(direccion, None)
        return True

def instantanea(roles=None):
    """Conexiones activas como (direccion, socket, lock). `roles` filtra por tipo de entidad."""
    with _lock:
        return [(d, s, _locks_envio[d]) for d, s in conexiones.items()
                if roles is None or _metadatos[d]["role"] in roles]

def direcciones():
    with _lock:
        return list(conexiones)

def actualizar_identidad(direccion, node_id, role="unknown", endpoint=None, api_endpoint=None,
                         cell_type=None, service=None):
    with _lock:
        metadata = _metadatos.get(direccion)
        if metadata is None:
            return
        metadata.update({
            "node_id": node_id, "role": role,
            "endpoint": endpoint, "api_endpoint": api_endpoint,
            "cell_type": cell_type, "service": service,
        })

def topologia():
    with _lock:
        return [dict(metadata) for metadata in _metadatos.values()]

def identidad(direccion):
    """Quién está al otro lado de una conexión: node_id, role y address (o None si ya no existe)."""
    with _lock:
        metadata = _metadatos.get(direccion)
        if metadata is None:
            return None
        return {"node_id": metadata["node_id"], "role": metadata["role"], "address": metadata["address"]}

def cerrar_todas():
    with _lock:
        sockets = list(conexiones.values())
        conexiones.clear()
        _locks_envio.clear()
        _metadatos.clear()
    for conexion in sockets:
        try:
            conexion.shutdown(2)
        except OSError:
            pass
        try:
            conexion.close()
        except OSError:
            pass
