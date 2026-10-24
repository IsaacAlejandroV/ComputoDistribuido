import json
import socket
import threading

from logger import registrar_evento
import peers

conexiones_salientes = {}
_objetivos = set()
_lock_salientes = threading.RLock()
_detener = threading.Event()
_node_id = "Desconocido"
_listen_port = None
_api_port = None


def configurar_identidad(node_id, listen_port, api_port=None):
    global _node_id, _listen_port, _api_port
    _node_id = node_id
    _listen_port = listen_port
    _api_port = api_port


def conectar_a_peer(ip, puerto, mi_node_id=None):
    """Configura una conexión saliente persistente hacia otro nodo."""
    direccion = f"{ip}:{puerto}"
    try:
        destino = (ip, int(puerto))
    except (TypeError, ValueError):
        print(f"[-] Puerto inválido para {direccion}")
        return

    with _lock_salientes:
        if direccion in _objetivos:
            print(f"\n[!] Ya está configurada la conexión a {direccion}")
            return
        _objetivos.add(direccion)

    threading.Thread(
        target=_mantener_conexion,
        args=(direccion, destino, mi_node_id or _node_id),
        daemon=True,
    ).start()


def _mantener_conexion(direccion, destino, mi_node_id):
    espera = 1
    while not _detener.is_set():
        cliente = None
        registrar_evento(f"INTENTO CONEXIÓN SALIENTE -> Hacia {direccion}")
        try:
            cliente = socket.create_connection(destino, timeout=5)
            cliente.settimeout(None)
            with _lock_salientes:
                conexiones_salientes[direccion] = cliente
            peers.registrar(direccion, cliente, "saliente")
            registrar_evento(f"CONEXIÓN SALIENTE EXITOSA -> A {direccion}")
            enviar_por_socket(direccion, cliente, {
                "type": "HELLO", "node_id": mi_node_id,
                "role": "node", "listen_port": _listen_port,
                "api_port": _api_port,
            })
            espera = 1

            # Importación diferida para evitar client -> server -> client al cargar.
            from server import leer_conexion
            leer_conexion(cliente, destino, direccion, "SALIENTE")
        except OSError as e:
            if not _detener.is_set():
                registrar_evento(
                    f"FALLO CONEXIÓN SALIENTE -> {direccion} ({e}); reintento en {espera}s"
                )
        finally:
            if cliente is not None:
                peers.eliminar(direccion, cliente)
                with _lock_salientes:
                    if conexiones_salientes.get(direccion) is cliente:
                        conexiones_salientes.pop(direccion, None)
                try:
                    cliente.close()
                except OSError:
                    pass

        if not _detener.wait(espera):
            espera = min(espera * 2, 10)

    with _lock_salientes:
        _objetivos.discard(direccion)


def enviar_por_socket(direccion, socket_peer, mensaje_dict):
    datos = (json.dumps(mensaje_dict) + "\n").encode("utf-8")
    for actual, conexion, lock_envio in peers.instantanea():
        if actual == direccion and conexion is socket_peer:
            with lock_envio:
                socket_peer.sendall(datos)
            return
    raise OSError("la conexión ya no está registrada")


def enviar_mensaje_a_todos(mensaje_dict, excluir=None, roles=None):
    """
    Broadcast: difunde un mensaje a todas las conexiones activas (nodos y
    células), salvo a `excluir` (quien nos lo entregó). `roles` limita el
    envío a ciertos tipos de entidad (p. ej. PING solo entre nodos).
    Devuelve a cuántas conexiones se entregó.
    """
    try:
        datos = (json.dumps(mensaje_dict) + "\n").encode("utf-8")
    except (TypeError, ValueError) as e:
        registrar_evento(f"MENSAJE DESCARTADO -> No serializable a JSON: {e}")
        return 0

    enviados = 0
    for direccion, socket_peer, lock_envio in peers.instantanea(roles):
        if direccion == excluir:
            continue
        try:
            with lock_envio:
                socket_peer.sendall(datos)
            enviados += 1
        except OSError as e:
            registrar_evento(f"DESCONEXIÓN -> Error de envío a {direccion}: {e}")
            peers.eliminar(direccion, socket_peer)
            with _lock_salientes:
                if conexiones_salientes.get(direccion) is socket_peer:
                    conexiones_salientes.pop(direccion, None)
            try:
                socket_peer.close()
            except OSError:
                pass
    return enviados


def hay_conexiones():
    return bool(peers.direcciones())


def direcciones_salientes():
    with _lock_salientes:
        return list(conexiones_salientes)


def detener_cliente():
    _detener.set()
    peers.cerrar_todas()
