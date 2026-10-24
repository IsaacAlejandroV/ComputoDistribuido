import json
import os
import threading
import socket

from logger import registrar_evento

_lock = threading.RLock()
_archivo = None
_propio = None
_conectar = None
_conocidos = set()
_puerto_propio = None
_ips_locales = {"127.0.0.1", "localhost", "::1"}
_guardar = True


def configurar(archivo, endpoint_propio, conectar, guardar=True):
    """
    `guardar=False` mantiene en memoria los nodos descubiertos sin reescribir
    el archivo de conexiones (útil para que la demo arranque siempre igual).
    """
    global _archivo, _propio, _conectar, _puerto_propio, _guardar
    _archivo = archivo
    _guardar = guardar
    _propio = endpoint_propio
    _conectar = conectar
    try:
        _puerto_propio = int(endpoint_propio.rsplit(":", 1)[1])
        for info in socket.getaddrinfo(socket.gethostname(), None):
            _ips_locales.add(info[4][0])
    except (OSError, ValueError):
        _puerto_propio = None
    with _lock:
        _conocidos.clear()


def cargar(endpoints):
    with _lock:
        for endpoint in endpoints:
            if _valido(endpoint) and not _es_propio(endpoint):
                _conocidos.add(endpoint)


def conocidos():
    with _lock:
        return sorted(_conocidos)


def descubrir(endpoint, conectar=True):
    """Guarda un nodo descubierto y, opcionalmente, abre conexión hacia él."""
    if not _valido(endpoint) or _es_propio(endpoint):
        return False
    with _lock:
        if endpoint in _conocidos:
            return False
        _conocidos.add(endpoint)
        _persistir()
    registrar_evento(f"NODO DESCUBIERTO -> {endpoint}")
    if conectar and _conectar:
        ip, puerto = endpoint.rsplit(":", 1)
        _conectar(ip, puerto)
    return True


def _valido(endpoint):
    if not isinstance(endpoint, str) or ":" not in endpoint:
        return False
    host, puerto = endpoint.rsplit(":", 1)
    try:
        numero = int(puerto)
    except ValueError:
        return False
    return bool(host.strip()) and 1 <= numero <= 65535


def _es_propio(endpoint):
    if endpoint == _propio:
        return True
    try:
        host, puerto = endpoint.rsplit(":", 1)
        if int(puerto) != _puerto_propio:
            return False
        direcciones = {info[4][0] for info in socket.getaddrinfo(host, None)}
        return bool(direcciones & _ips_locales)
    except (OSError, ValueError):
        return False


def _persistir():
    if not _archivo or not _guardar:
        return
    temporal = _archivo + ".tmp"
    try:
        os.makedirs(os.path.dirname(_archivo), exist_ok=True)
        with open(temporal, "w", encoding="utf-8") as f:
            json.dump(sorted(_conocidos), f, ensure_ascii=False, indent=4)
            f.write("\n")
        os.replace(temporal, _archivo)
    except OSError as e:
        registrar_evento(f"ERROR -> No se pudo actualizar {_archivo}: {e}")
