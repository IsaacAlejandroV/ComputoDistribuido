"""
Célula servidor de la calculadora ADS.

Un mismo programa se configura para atender un servicio: suma, resta,
multiplicación o división. Se pueden ejecutar tantas instancias como se quiera.

    python src/celula_servidor.py --servicio SUM --id SRV_SUM_N1 --nodo 127.0.0.1:8071

Estrategia para evitar respuestas duplicadas (hay un servidor de cada tipo en
cada nodo y TODOS reciben la solicitud por broadcast):

  1. Retardo proporcional a la distancia. Al recibir <SVC>_REQ, el servidor no
     responde de inmediato: programa su respuesta tras
         retardo = retardo_por_salto_ms * (saltos - 1) + desempate
     donde `saltos` es el número de nodos que recorrió la solicitud (campo
     `path` que llenan los nodos) y `desempate` es un valor determinista entre
     0 y ventana_desempate_ms calculado con hash(id_servidor + id_solicitud).
     Así, el servidor conectado al mismo nodo que la GUI suele responder primero.
  2. Supresión por escucha. Las respuestas también se difunden por broadcast,
     así que los demás servidores del mismo servicio reciben <SVC>_RES. Si
     llega una respuesta para una solicitud que tenían pendiente, cancelan la
     suya.
  3. Respaldo en la GUI. Si por latencia dos servidores llegan a responder,
     la GUI acepta solo la primera respuesta por request_id y descarta el resto.

No hay coordinador: cada servidor decide por sí mismo, y si el servidor más
cercano falla, otro responde un poco después (sin punto único de fallo).
"""
import argparse
import hashlib
import threading
import time

import comun
import content_codes as cc
import logger
from logger import registrar
from acp import ACP, _corto
from asm_calculadora import calcular, ErrorOperacion

MAX_RECORDADAS = 10000


class CelulaServidor:
    def __init__(self, cell_id, servicio, nodos, cfg):
        self.cell_id = cell_id
        self.servicio = servicio
        self.req, self.res, self.simbolo, self.nombre = cc.SERVICIOS[servicio]
        self.retardo_salto = cfg["retardo_por_salto_ms"] / 1000.0
        self.ventana = cfg["ventana_desempate_ms"]
        self._pendientes = {}        # request_id -> Timer
        self._resueltas = set()      # request_id ya atendidas (por mí o por otro)
        self._orden = []
        self._lock = threading.Lock()
        self.atendidas = 0
        self.suprimidas = 0
        self.acp = ACP(cell_id, "SERVER", nodos, {self.req, self.res}, self._al_recibir,
                       service=servicio, ttl=cfg["ttl"], mostrar_ignorados=cfg["mostrar_ignorados"])

    def iniciar(self):
        registrar("INICIO", f"Célula servidor {self.cell_id} | servicio {self.nombre} ({self.req}/{self.res}) "
                            f"| nodos={self.acp.nodos}")
        self.acp.iniciar()

    def detener(self):
        with self._lock:
            for t in self._pendientes.values():
                t.cancel()
            self._pendientes.clear()
        self.acp.detener()

    # ---------- estrategia anti-duplicados ----------

    def calcular_retardo(self, request_id, ruta):
        saltos = max(1, len(ruta or []))
        h = int(hashlib.sha1(f"{self.cell_id}|{request_id}".encode()).hexdigest(), 16)
        desempate = (h % (int(self.ventana) + 1)) / 1000.0 if self.ventana else 0.0
        return self.retardo_salto * (saltos - 1) + desempate, saltos

    def _marcar_resuelta(self, request_id):
        if request_id in self._resueltas:
            return
        self._resueltas.add(request_id)
        self._orden.append(request_id)
        if len(self._orden) > MAX_RECORDADAS:
            self._resueltas.discard(self._orden.pop(0))

    def _al_recibir(self, mensaje):
        codigo = mensaje["content_code"]
        if codigo == self.req:
            self._programar(mensaje)
        elif codigo == self.res:
            self._escuchar_respuesta(mensaje)

    def _programar(self, solicitud):
        request_id = solicitud["msg_id"]
        retardo, saltos = self.calcular_retardo(request_id, solicitud.get("path"))
        with self._lock:
            if request_id in self._resueltas or request_id in self._pendientes:
                registrar("DROP", f"solicitud {_corto(request_id)} ya resuelta: no se atiende")
                return
            timer = threading.Timer(retardo, self._responder, args=(solicitud,))
            timer.daemon = True
            self._pendientes[request_id] = timer
        registrar("ESPERA", f"{self.req} req={_corto(request_id)} de {solicitud['node_id']} a {saltos} salto(s): "
                            f"respondo en {int(retardo * 1000)} ms si nadie lo hace antes")
        timer.start()

    def _escuchar_respuesta(self, respuesta):
        request_id = respuesta["request_id"]
        with self._lock:
            timer = self._pendientes.pop(request_id, None)
            self._marcar_resuelta(request_id)
        if timer is not None:
            timer.cancel()
            self.suprimidas += 1
            registrar("SUPRIME", f"{respuesta['node_id']} ya respondió req={_corto(request_id)}: "
                                 f"cancelo mi respuesta (suprimidas={self.suprimidas})")

    def _responder(self, solicitud):
        request_id = solicitud["msg_id"]
        with self._lock:
            if self._pendientes.pop(request_id, None) is None:
                return  # otro servidor respondió mientras esperaba
            self._marcar_resuelta(request_id)

        operandos = solicitud["data"].get("operands")
        try:
            resultado, error = calcular(self.servicio, operandos), None
        except ErrorOperacion as e:
            resultado, error = None, str(e)

        datos = {"result": resultado, "error": error, "operands": operandos, "operation": self.simbolo}
        msg_id = self.acp.publicar(self.res, datos, request_id=request_id,
                                   request_origin=solicitud["node_id"], service=self.servicio)
        if msg_id:
            self.atendidas += 1
            texto = error if error else resultado
            a, b = (operandos + [None, None])[:2] if isinstance(operandos, list) else (None, None)
            registrar("TX", f"{self.res} id={_corto(msg_id)} req={_corto(request_id)} -> "
                            f"{a} {self.simbolo} {b} = {texto} (atendidas={self.atendidas})")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Célula servidor de la calculadora ADS")
    parser.add_argument("--servicio", required=True, help="SUM, SUB, MUL o DIV (también suma, resta, +, -...)")
    comun.agregar_argumentos_comunes(parser)
    args = parser.parse_args(argv)
    try:
        servicio = cc.normalizar_servicio(args.servicio)
    except ValueError as e:
        parser.error(str(e))

    cfg = comun.cargar_config(args.config)
    logger.configurar(comun.LOG_DIR, args.id)
    comun.titulo_consola(f"{args.id} - Servidor {cc.SERVICIOS[servicio][3]}")

    celula = CelulaServidor(args.id, servicio, args.nodo, cfg)
    celula.iniciar()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    celula.detener()
    registrar("FIN", f"Célula {args.id} detenida | atendidas={celula.atendidas} suprimidas={celula.suprimidas}")


if __name__ == "__main__":
    main()
