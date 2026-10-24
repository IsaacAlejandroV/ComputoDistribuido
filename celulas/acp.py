"""
ACP (Autonomous Control Processor) de una célula.

Es la parte de comunicación que comparten la célula GUI y la célula servidor:
  - Se conecta como cliente a uno o más nodos del Campo de Datos y se
    identifica con HELLO (role="cell", cell_type, service).
  - Reconecta solo si el nodo se cae.
  - Valida el formato, descarta duplicados por msg_id y entrega a la célula
    únicamente los Códigos de Contenido que le interesan.
  - Publica mensajes nuevos con msg_id único, TTL y ruta vacía.

El ACP no toma decisiones de negocio: eso lo hacen la GUI y el ASM.
"""
import datetime
import json
import socket
import threading
import time
import uuid
from collections import deque

import content_codes
from logger import registrar

MAX_LINEA = 65536
MAX_MENSAJES_RECORDADOS = 10000
TTL_POR_DEFECTO = 16


def _corto(msg_id):
    return str(msg_id)[:8]


def ruta_texto(mensaje):
    ruta = mensaje.get("path") or []
    return "→".join(ruta) if ruta else "(directo)"


class ACP:
    def __init__(self, cell_id, cell_type, nodos, intereses, al_recibir,
                 service=None, ttl=TTL_POR_DEFECTO, mostrar_ignorados=True):
        self.cell_id = cell_id
        self.cell_type = cell_type
        self.service = service
        self.nodos = list(nodos)
        self.intereses = set(intereses)
        self.al_recibir = al_recibir        # callback(mensaje) para lo que sí interesa
        self.ttl = ttl
        self.mostrar_ignorados = mostrar_ignorados
        self.activo = False
        self._conexiones = {}               # "ip:puerto" -> socket
        self._vistos = set()                # msg_id ya procesados
        self._orden_vistos = deque()
        self._lock = threading.Lock()
        self._envio = threading.Lock()
        self.al_cambiar_conexion = None     # callback(n_conexiones) opcional

        for codigo in sorted(self.intereses - content_codes.TODOS):
            registrar("WARN", f"El interés {codigo!r} no está en content_codes.py")

    # ---------- conexión con el Campo de Datos ----------

    def iniciar(self):
        self.activo = True
        for direccion in self.nodos:
            try:
                ip, puerto = direccion.rsplit(":", 1)
                destino = (ip, int(puerto))
            except ValueError:
                registrar("ERROR", f"Nodo inválido: {direccion!r} (usa IP:PUERTO)")
                continue
            threading.Thread(target=self._mantener_conexion, args=(direccion, destino), daemon=True).start()

    def detener(self):
        self.activo = False
        with self._lock:
            sockets = list(self._conexiones.values())
        for s in sockets:
            try:
                s.close()
            except OSError:
                pass

    def conectado(self):
        with self._lock:
            return len(self._conexiones)

    def _notificar_conexion(self):
        if self.al_cambiar_conexion:
            try:
                self.al_cambiar_conexion(self.conectado())
            except Exception:
                pass

    def _mantener_conexion(self, direccion, destino):
        espera = 1
        while self.activo:
            try:
                s = socket.create_connection(destino, timeout=5)
            except OSError as e:
                registrar("ERROR", f"No se pudo conectar a {direccion}: {e}. Reintento en {espera}s")
                time.sleep(espera)
                espera = min(espera * 2, 10)
                continue

            s.settimeout(None)
            espera = 1
            with self._lock:
                self._conexiones[direccion] = s
            registrar("CONN", f"Conectado al nodo {direccion}")
            # Protocolo de conexión: la célula declara qué tipo de entidad es.
            self._enviar_a(s, {
                "type": "HELLO", "node_id": self.cell_id, "role": "cell",
                "cell_type": self.cell_type, "service": self.service,
            })
            self._notificar_conexion()

            self._leer(s, direccion)

            with self._lock:
                self._conexiones.pop(direccion, None)
            try:
                s.close()
            except OSError:
                pass
            self._notificar_conexion()
            if self.activo:
                registrar("DISCONN", f"Conexión perdida con {direccion}")

    def _leer(self, s, direccion):
        buffer = b""
        while self.activo:
            try:
                data = s.recv(4096)
            except OSError:
                break
            if not data:
                break
            buffer += data
            while b"\n" in buffer:
                linea, buffer = buffer.split(b"\n", 1)
                linea = linea.strip()
                if linea:
                    self._recibir(linea.decode("utf-8", errors="replace"), direccion)
            if len(buffer) > MAX_LINEA:
                registrar("DROP", f"más de {MAX_LINEA} bytes sin salto de línea | {direccion}")
                buffer = b""

    # ---------- entrada: Campo de Datos -> ACP -> célula ----------

    def _recordar(self, msg_id):
        if msg_id in self._vistos:
            return False
        self._vistos.add(msg_id)
        self._orden_vistos.append(msg_id)
        while len(self._orden_vistos) > MAX_MENSAJES_RECORDADOS:
            self._vistos.discard(self._orden_vistos.popleft())
        return True

    def _recibir(self, texto, direccion):
        try:
            mensaje = json.loads(texto)
        except (ValueError, RecursionError):
            registrar("DROP", f"no es JSON válido | {direccion} | {texto[:60]!r}")
            return
        if not isinstance(mensaje, dict) or mensaje.get("type") != "CONTENT":
            return  # HELLO, PING, PEERS...: mensajes de control de la malla

        motivo = self._validar(mensaje)
        if motivo:
            registrar("DROP", f"{motivo} | {direccion}")
            return

        msg_id = mensaje["msg_id"]
        with self._lock:
            nuevo = self._recordar(msg_id)
        if not nuevo:
            registrar("DROP", f"duplicado msg_id={_corto(msg_id)} (ya procesado)")
            return

        codigo = mensaje["content_code"]
        if codigo not in self.intereses:
            if self.mostrar_ignorados:
                registrar("IGNORE", f"{codigo} id={_corto(msg_id)} de {mensaje['node_id']} "
                                    f"ruta={ruta_texto(mensaje)} (no es de mi interés)")
            return

        registrar("RX", f"{codigo} id={_corto(msg_id)} de {mensaje['node_id']} ruta={ruta_texto(mensaje)}")
        try:
            self.al_recibir(mensaje)
        except Exception as e:
            registrar("ERROR", f"Falla procesando {codigo}: {e}")

    @staticmethod
    def _validar(mensaje):
        for campo in ("node_id", "msg_id", "content_code"):
            valor = mensaje.get(campo)
            if not isinstance(valor, str) or not valor.strip():
                return f"falta {campo} (texto no vacío)"
        if not isinstance(mensaje.get("data"), dict):
            return "data debe ser un objeto"
        if content_codes.es_respuesta(mensaje["content_code"]):
            if not isinstance(mensaje.get("request_id"), str):
                return "respuesta sin request_id"
        return None

    # ---------- salida: célula -> ACP -> Campo de Datos ----------

    def publicar(self, codigo, data, **campos_extra):
        """
        Crea un mensaje nuevo con identificador único y lo envía a los nodos
        conectados. Devuelve el msg_id (o None si no pudo enviarse).
        """
        if codigo not in content_codes.TODOS:
            registrar("DROP", f"content_code desconocido: {codigo!r}")
            return None
        msg_id = str(uuid.uuid4())
        mensaje = {
            "type": "CONTENT",
            "msg_id": msg_id,
            "content_code": codigo,
            "node_id": self.cell_id,          # célula que originó el mensaje
            "cell_type": self.cell_type,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds"),
            "ttl": self.ttl,
            "path": [],
            "data": data,
        }
        mensaje.update(campos_extra)
        with self._lock:
            self._recordar(msg_id)  # si la malla nos lo devuelve, se descarta
            destinos = list(self._conexiones.values())

        enviados = sum(1 for s in destinos if self._enviar_a(s, mensaje))
        if enviados == 0:
            registrar("ERROR", f"{codigo} id={_corto(msg_id)} no se pudo enviar: sin conexión a ningún nodo")
            return None
        return msg_id

    def _enviar_a(self, s, mensaje):
        try:
            datos = (json.dumps(mensaje, ensure_ascii=False) + "\n").encode("utf-8")
        except (TypeError, ValueError) as e:
            registrar("DROP", f"el dato no es serializable a JSON: {e}")
            return False
        try:
            with self._envio:
                s.sendall(datos)
            return True
        except OSError:
            try:
                s.close()  # el hilo lector lo detecta y reconecta
            except OSError:
                pass
            return False
