"""
Nodo del Campo de Datos (ADS): servidor TCP + procesamiento del protocolo.

El nodo NO interpreta las operaciones de la calculadora. Su trabajo es:
  1. Aceptar conexiones de nodos y de células (protocolo de conexión, HELLO).
  2. Difundir por broadcast todo mensaje CONTENT a los demás nodos y a sus
     células conectadas, excepto a quien se lo entregó.
  3. Impedir ciclos: descarta cualquier msg_id ya procesado (memoria temporal
     acotada) y aplica un TTL como segunda barrera.
  4. Anotar en el mensaje la ruta de nodos recorrida (`path`) para que el
     recorrido sea observable en la bitácora.
"""
import json
import socket
import threading
import uuid
from collections import deque

from client import enviar_mensaje_a_todos, enviar_por_socket
from logger import registrar_evento
import peers
import discovery
import content_log

# --- Registro temporal de mensajes procesados (prevención de ciclos) ---
mensajes_vistos = set()  # msg_id ya procesados por este nodo
mis_mensajes = set()     # msg_id generados por este nodo (para reconocer sus ACK)
_orden_vistos = deque()
_orden_propios = deque()
_lock_mensajes = threading.RLock()
MAX_MENSAJES_RECORDADOS = 10000  # ventana FIFO: el registro es temporal, no crece sin límite

mi_identificador = "Desconocido"
mi_puerto = None
mi_api_puerto = None

TTL_POR_DEFECTO = 16   # saltos máximos si la célula no indica TTL
MOSTRAR_PING = False   # los latidos llenan la consola; se pueden activar en config

ROLES_VALIDOS = ("node", "cell", "app", "unknown")
ROLES_NODO = ("node", "unknown")  # destinos de PING/PEERS/TEXT/ACK: solo la malla


def _recordar(conjunto, orden, msg_id):
    if msg_id in conjunto:
        return False
    conjunto.add(msg_id)
    orden.append(msg_id)
    while len(orden) > MAX_MENSAJES_RECORDADOS:
        conjunto.discard(orden.popleft())
    return True


def registrar_mensaje_propio(msg_id):
    with _lock_mensajes:
        _recordar(mensajes_vistos, _orden_vistos, msg_id)
        _recordar(mis_mensajes, _orden_propios, msg_id)


def _registrar_si_nuevo(msg_id):
    with _lock_mensajes:
        return _recordar(mensajes_vistos, _orden_vistos, msg_id)


def _es_mensaje_propio(msg_id):
    with _lock_mensajes:
        return msg_id in mis_mensajes


def set_identificador(node_id, puerto=None, api_puerto=None, ttl=None, mostrar_ping=None):
    global mi_identificador, mi_puerto, mi_api_puerto, TTL_POR_DEFECTO, MOSTRAR_PING
    mi_identificador = node_id
    mi_puerto = puerto
    mi_api_puerto = api_puerto
    if ttl is not None:
        TTL_POR_DEFECTO = ttl
    if mostrar_ping is not None:
        MOSTRAR_PING = mostrar_ping


TIPOS_VALIDOS = ("HELLO", "PING", "TEXT", "ACK", "CONTENT", "PEERS")
MAX_LINEA = 65536  # caracteres máximos de un mensaje sin salto de línea


def _texto_no_vacio(valor):
    return isinstance(valor, str) and valor.strip() != ""


def _puerto_valido(port):
    return isinstance(port, int) and not isinstance(port, bool) and 1 <= port <= 65535


def validar_mensaje(datos):
    """
    Devuelve None si el mensaje cumple el formato del protocolo, o un texto
    con el motivo por el que debe descartarse. Se aceptan campos extra.
    """
    if not isinstance(datos, dict):
        return "no es un objeto JSON"
    tipo = datos.get("type")
    if tipo not in TIPOS_VALIDOS:
        return f"type inválido: {repr(tipo)[:40]}"
    if not _texto_no_vacio(datos.get("node_id")):
        return "falta node_id (texto no vacío)"
    msg_id = datos.get("msg_id")
    if msg_id is not None and not _texto_no_vacio(msg_id):
        return "msg_id debe ser texto no vacío"
    if tipo in ("PING", "TEXT", "ACK", "CONTENT", "PEERS") and msg_id is None:
        return f"{tipo} sin msg_id"
    if tipo == "TEXT" and not isinstance(datos.get("text"), str):
        return "TEXT sin campo text (texto)"
    if tipo == "CONTENT":
        if not _texto_no_vacio(datos.get("content_code")):
            return "CONTENT sin content_code (texto no vacío)"
        if "data" not in datos:
            return "CONTENT sin campo data"
        ttl = datos.get("ttl")
        if ttl is not None and (not isinstance(ttl, int) or isinstance(ttl, bool)):
            return "CONTENT con ttl no entero"
        ruta = datos.get("path")
        if ruta is not None and (not isinstance(ruta, list) or any(not isinstance(n, str) for n in ruta)):
            return "CONTENT con path inválido (lista de textos)"
    if tipo == "ACK":
        if not _texto_no_vacio(datos.get("ack_msg_id")):
            return "ACK sin ack_msg_id (texto no vacío)"
    if tipo == "HELLO":
        role = datos.get("role", "unknown")
        if role not in ROLES_VALIDOS:
            return "HELLO con role inválido"
        if role == "node" and datos.get("listen_port") is not None and not _puerto_valido(datos["listen_port"]):
            return "HELLO con listen_port inválido"
        if role == "node" and datos.get("api_port") is not None and not _puerto_valido(datos["api_port"]):
            return "HELLO con api_port inválido"
        if role == "cell" and not _texto_no_vacio(datos.get("cell_type")):
            return "HELLO de célula sin cell_type"
    if tipo == "PEERS":
        endpoints = datos.get("peers")
        if not isinstance(endpoints, list) or any(not isinstance(p, str) for p in endpoints):
            return "PEERS sin lista de direcciones"
    return None


def descartar_mensaje(motivo, crudo, direccion):
    muestra = repr(crudo[:60]) + ("..." if len(crudo) > 60 else "")
    registrar_evento(f"MENSAJE DESCARTADO -> {motivo} | PEER: {direccion} | CONTENIDO: {muestra}")


def _quien(direccion):
    ident = peers.identidad(direccion)
    if not ident or not ident.get("node_id"):
        return direccion
    return f"{ident['node_id']}({ident['role']})"


def _procesar_hello(datos, addr, direccion):
    origen = datos["node_id"]
    role = datos.get("role", "unknown")
    endpoint = None
    api_endpoint = None
    cell_type = datos.get("cell_type")
    service = datos.get("service")
    if role == "node" and datos.get("listen_port"):
        endpoint = f"{addr[0]}:{datos['listen_port']}"
        discovery.descubrir(endpoint, conectar=False)
    if role == "node" and datos.get("api_port"):
        api_endpoint = f"http://{addr[0]}:{datos['api_port']}/topology"
    peers.actualizar_identidad(direccion, origen, role, endpoint, api_endpoint, cell_type, service)

    if role == "node":
        registrar_evento(f"NODO CONECTADO -> {origen} ({direccion})")
        anuncio_id = str(uuid.uuid4())
        registrar_mensaje_propio(anuncio_id)
        enviar_mensaje_a_todos({
            "type": "PEERS", "node_id": mi_identificador,
            "msg_id": anuncio_id, "peers": discovery.conocidos(),
        }, roles=ROLES_NODO)
    else:
        detalle = f"{cell_type}" + (f" [{service}]" if service else "")
        registrar_evento(f"CÉLULA CONECTADA -> {origen} tipo={detalle} ({direccion})")


def _procesar_content(datos, direccion, msg_id):
    """Broadcast de un mensaje con Código de Contenido (solicitud o respuesta)."""
    origen = datos["node_id"]
    codigo = datos["content_code"]
    ttl = datos.get("ttl", TTL_POR_DEFECTO)
    if ttl <= 0:
        registrar_evento(f"TTL AGOTADO -> {codigo} id={msg_id[:8]} de {origen}: no se retransmite")
        return

    # Datos de control del broadcast: un salto menos y este nodo en la ruta.
    ruta = list(datos.get("path") or []) + [mi_identificador]
    reenviado = dict(datos, ttl=ttl - 1, path=ruta)

    content_log.registrar(origen, codigo, datos["data"], msg_id, peers.identidad(direccion))
    enviados = enviar_mensaje_a_todos(reenviado, excluir=direccion)

    extra = f" req={datos['request_id'][:8]}" if isinstance(datos.get("request_id"), str) else ""
    registrar_evento(
        f"BROADCAST {codigo:<7} id={msg_id[:8]}{extra} origen={origen} "
        f"recibido_de={_quien(direccion)} ruta={'→'.join(ruta)} ttl={ttl - 1} "
        f"-> reenviado a {enviados} conexión(es)"
    )


def procesar_mensaje(mensaje_str, addr):
    """
    Lee el JSON, descarta lo que no cumpla el formato y ejecuta el protocolo
    del Campo de Datos (broadcast con prevención de ciclos).
    """
    direccion = f"{addr[0]}:{addr[1]}"  # quién nos lo entregó
    try:
        try:
            datos = json.loads(mensaje_str)
        except (ValueError, RecursionError):
            descartar_mensaje("no es JSON válido", mensaje_str, direccion)
            return

        motivo = validar_mensaje(datos)
        if motivo:
            descartar_mensaje(motivo, mensaje_str, direccion)
            return

        tipo = datos["type"]
        origen = datos["node_id"]
        msg_id = datos.get("msg_id")

        # ==============================================================
        # PREVENCIÓN DE CICLOS: un msg_id ya procesado no se retransmite
        # ==============================================================
        if msg_id and not _registrar_si_nuevo(msg_id):
            if tipo == "CONTENT":
                registrar_evento(
                    f"DUPLICADO DESCARTADO -> {datos['content_code']} id={msg_id[:8]} "
                    f"(copia llegada desde {_quien(direccion)})"
                )
            return

        if tipo == "HELLO":
            _procesar_hello(datos, addr, direccion)

        elif tipo == "PING":
            if MOSTRAR_PING:
                registrar_evento(f"PING -> origen {origen}, msg_id {msg_id[:8]}")
            enviar_mensaje_a_todos(datos, excluir=direccion, roles=ROLES_NODO)

        elif tipo == "TEXT":
            texto = datos.get("text", "(sin contenido)")
            registrar_evento(f"MENSAJE RECIBIDO -> TIPO: TEXT, ORIGEN: {origen}, TEXTO: '{texto}'")
            enviar_mensaje_a_todos(datos, excluir=direccion, roles=ROLES_NODO)
            if origen != mi_identificador:
                ack_msg = {
                    "type": "ACK", "node_id": mi_identificador,
                    "msg_id": str(uuid.uuid4()), "ack_msg_id": msg_id,
                }
                registrar_mensaje_propio(ack_msg["msg_id"])
                enviar_mensaje_a_todos(ack_msg, roles=ROLES_NODO)

        elif tipo == "ACK":
            ack_id = datos.get("ack_msg_id")
            if _es_mensaje_propio(ack_id):
                registrar_evento(f"ACK RECIBIDO -> {origen} confirmó nuestro mensaje {ack_id[:8]}")
            enviar_mensaje_a_todos(datos, excluir=direccion, roles=ROLES_NODO)

        elif tipo == "CONTENT":
            _procesar_content(datos, direccion, msg_id)

        elif tipo == "PEERS":
            for endpoint in datos["peers"]:
                discovery.descubrir(endpoint, conectar=True)
            enviar_mensaje_a_todos(datos, excluir=direccion, roles=ROLES_NODO)

    except Exception as e:
        # Un fallo procesando un mensaje no debe tumbar el hilo de la conexión
        registrar_evento(f"ERROR -> Falla procesando mensaje de {direccion}: {e}")


def leer_conexion(conn, addr, direccion=None, clase="ENTRANTE"):
    """Lee mensajes delimitados por salto de línea desde cualquier socket."""
    direccion = direccion or f"{addr[0]}:{addr[1]}"
    buffer = ""
    while True:
        try:
            data = conn.recv(4096)
            if not data:
                break
            buffer += data.decode('utf-8', errors='replace')
            while '\n' in buffer:
                linea, buffer = buffer.split('\n', 1)
                if linea.strip():
                    procesar_mensaje(linea.strip(), addr)
            if len(buffer) > MAX_LINEA:
                descartar_mensaje(f"más de {MAX_LINEA} caracteres sin salto de línea", buffer, direccion)
                buffer = ""
        except (ConnectionResetError, OSError):
            break

    quien = _quien(direccion)
    peers.eliminar(direccion, conn)
    registrar_evento(f"DESCONEXIÓN {clase} -> {quien}")


def manejar_cliente(conn, addr):
    """Atiende una conexión entrante (nodo o célula) en su propio hilo."""
    direccion = f"{addr[0]}:{addr[1]}"
    registrar_evento(f"CONEXIÓN ENTRANTE -> Aceptada desde {direccion}")

    # Toda conexión entrante entra al registro compartido: el broadcast debe
    # alcanzar tanto a nodos como a células que se conectaron hacia nosotros.
    peers.registrar(direccion, conn, "entrante")
    try:
        enviar_por_socket(direccion, conn, {
            "type": "HELLO", "node_id": mi_identificador,
            "role": "node", "listen_port": mi_puerto,
            "api_port": mi_api_puerto,
        })
    except OSError:
        pass
    leer_conexion(conn, addr, direccion, "ENTRANTE")
    try:
        conn.close()
    except OSError:
        pass


def iniciar_servidor(host, port, listo=None):
    """Inicia el servidor TCP y se queda escuchando conexiones."""
    servidor = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    servidor.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        servidor.bind((host, port))
        servidor.listen(64)
        registrar_evento(f"SERVIDOR INICIADO -> Escuchando en {host}:{port}")
        if listo is not None:
            listo.set()

        while True:
            conn, addr = servidor.accept()
            hilo_cliente = threading.Thread(target=manejar_cliente, args=(conn, addr), daemon=True)
            hilo_cliente.start()

    except Exception as e:
        registrar_evento(f"ERROR CRÍTICO -> Falla en el servidor TCP: {e}")
        if listo is not None:
            listo.set()
    finally:
        servidor.close()
