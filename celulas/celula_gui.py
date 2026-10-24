"""
Célula cliente (GUI) de la calculadora ADS.

    python src/celula_gui.py --id GUI_N1 --nodo 127.0.0.1:8071

Captura los operandos y la operación, genera la solicitud con un Código de
Contenido (SUM_REQ, SUB_REQ, MUL_REQ o DIV_REQ) y un identificador único, la
entrega a su nodo y espera la respuesta (<SVC>_RES) que la referencie mediante
request_id. Las respuestas a solicitudes de otras GUI también llegan por el
broadcast, pero se ignoran.

Modo sin ventana (pruebas o equipos sin entorno gráfico):
    python src/celula_gui.py --id GUI_T --nodo 127.0.0.1:8071 --sin-gui --operaciones "2+3" "10/4" "7*6" "5-9"
"""
import argparse
import queue
import re
import threading
import time

import comun
import content_codes as cc
import logger
from logger import registrar
from acp import ACP, _corto, ruta_texto


class ClienteCalculadora:
    """Lógica de la célula GUI, independiente de la ventana."""

    def __init__(self, cell_id, nodos, cfg, al_evento=None):
        self.cell_id = cell_id
        self.timeout = cfg["timeout_respuesta_s"]
        self.al_evento = al_evento or (lambda tipo, info: None)
        self._pendientes = {}   # request_id -> dict de la solicitud
        self._resueltas = {}    # request_id -> servidor que respondió primero
        self._lock = threading.Lock()
        self.acp = ACP(cell_id, "GUI", nodos, cc.RESPUESTAS, self._al_recibir,
                       ttl=cfg["ttl"], mostrar_ignorados=cfg["mostrar_ignorados"])
        self.acp.al_cambiar_conexion = lambda n: self.al_evento("conexion", {"nodos": n})
        self._activo = False

    def iniciar(self):
        registrar("INICIO", f"Célula GUI {self.cell_id} | nodos={self.acp.nodos}")
        self._activo = True
        self.acp.iniciar()
        threading.Thread(target=self._vigilar_timeouts, daemon=True).start()

    def detener(self):
        self._activo = False
        self.acp.detener()

    # ---------- solicitud ----------

    def solicitar(self, servicio, a, b):
        codigo = cc.codigo_solicitud(servicio)
        simbolo = cc.SERVICIOS[servicio][2]
        info = {"servicio": servicio, "codigo": codigo, "a": a, "b": b, "simbolo": simbolo,
                "t0": time.monotonic()}
        # Se registra antes de publicar: la respuesta podría llegar casi de inmediato.
        with self._lock:
            request_id = self.acp.publicar(codigo, {"operands": [a, b]})
            if request_id is None:
                return None
            info["request_id"] = request_id
            self._pendientes[request_id] = info
        registrar("REQ", f"{codigo} id={_corto(request_id)} -> {a} {simbolo} {b}")
        return request_id

    # ---------- respuesta ----------

    def _al_recibir(self, mensaje):
        request_id = mensaje["request_id"]
        servidor = mensaje["node_id"]
        with self._lock:
            info = self._pendientes.get(request_id)
            if info is not None and mensaje["content_code"] != cc.codigo_respuesta(info["servicio"]):
                registrar("DROP", f"{mensaje['content_code']} no corresponde a {info['codigo']} "
                                  f"req={_corto(request_id)}")
                return
            if info is not None:
                del self._pendientes[request_id]
                self._resueltas[request_id] = servidor
            primero = self._resueltas.get(request_id)

        if info is None:
            if primero is not None:
                registrar("DUPLIC", f"respuesta extra de {servidor} para req={_corto(request_id)} "
                                    f"descartada (ya respondió {primero})")
            else:
                registrar("AJENA", f"{mensaje['content_code']} req={_corto(request_id)} es para "
                                   f"{mensaje.get('request_origin', 'otra GUI')}: se ignora")
            return

        datos = mensaje["data"]
        latencia = int((time.monotonic() - info["t0"]) * 1000)
        resultado = {**info, "resultado": datos.get("result"), "error": datos.get("error"),
                     "servidor": servidor, "ruta": ruta_texto(mensaje), "latencia_ms": latencia,
                     "msg_id": mensaje["msg_id"]}
        texto = resultado["error"] or resultado["resultado"]
        registrar("RES", f"{mensaje['content_code']} id={_corto(mensaje['msg_id'])} req={_corto(request_id)} "
                         f"=> {info['a']} {info['simbolo']} {info['b']} = {texto} | servidor={servidor} "
                         f"ruta={resultado['ruta']} | {latencia} ms")
        self.al_evento("resultado", resultado)

    def _vigilar_timeouts(self):
        while self._activo:
            time.sleep(0.25)
            ahora = time.monotonic()
            vencidas = []
            with self._lock:
                for request_id, info in list(self._pendientes.items()):
                    if ahora - info["t0"] > self.timeout:
                        vencidas.append(self._pendientes.pop(request_id))
            for info in vencidas:
                registrar("TIMEOUT", f"{info['codigo']} req={_corto(info['request_id'])} sin respuesta "
                                     f"en {self.timeout}s (¿hay servidores {info['servicio']}?)")
                self.al_evento("timeout", info)


# =====================================================================
# Ventana (tkinter)
# =====================================================================

def _formatear(valor):
    if isinstance(valor, float):
        return f"{valor:.10g}"
    return str(valor)


def _parsear(texto):
    texto = texto.strip().replace(",", ".")
    if texto in ("", "-", ".", "-."):
        raise ValueError("número incompleto")
    valor = float(texto)
    return int(valor) if re.fullmatch(r"-?\d+", texto) else valor


class VentanaCalculadora:
    COLORES = {
        "fondo": "#1f2430", "panel": "#272d3b", "texto": "#e6e9ef", "tenue": "#9aa3b5",
        "tecla": "#343b4d", "operador": "#3d5a80", "igual": "#2a9d8f", "borrar": "#8d3b48",
        "ok": "#5fbf77", "error": "#e07a5f",
    }

    def __init__(self, cell_id, nodos, cfg):
        import tkinter as tk
        from tkinter import ttk, font as tkfont
        self.tk = tk
        self.cola = queue.Queue()
        self.cliente = ClienteCalculadora(cell_id, nodos, cfg, al_evento=lambda t, i: self.cola.put((t, i)))
        logger.agregar_oyente(lambda evento, linea: self.cola.put(("log", (evento, linea))))

        c = self.COLORES
        self.root = tk.Tk()
        self.root.title(f"Calculadora ADS — {cell_id}")
        self.root.configure(bg=c["fondo"])
        self.root.minsize(460, 640)
        base = tkfont.nametofont("TkDefaultFont").actual()["family"]
        self.f_display = (base, 26, "bold")
        self.f_expr = (base, 11)
        self.f_tecla = (base, 15, "bold")
        self.f_chico = (base, 9)

        self.actual = "0"         # número que se está escribiendo
        self.primero = None       # primer operando
        self.servicio = None      # operación seleccionada
        self.esperando = None     # request_id en curso
        self.nuevo_numero = True

        # --- encabezado ---
        cab = tk.Frame(self.root, bg=c["fondo"])
        cab.pack(fill="x", padx=14, pady=(12, 4))
        tk.Label(cab, text=f"Célula GUI  {cell_id}", bg=c["fondo"], fg=c["texto"],
                 font=(base, 12, "bold")).pack(side="left")
        self.lbl_estado = tk.Label(cab, text="● conectando…", bg=c["fondo"], fg=c["tenue"], font=self.f_chico)
        self.lbl_estado.pack(side="right")
        tk.Label(self.root, text=f"Nodo: {', '.join(nodos)}", bg=c["fondo"], fg=c["tenue"],
                 font=self.f_chico, anchor="w").pack(fill="x", padx=14)

        # --- pantalla ---
        pantalla = tk.Frame(self.root, bg=c["panel"])
        pantalla.pack(fill="x", padx=14, pady=8)
        self.lbl_expr = tk.Label(pantalla, text=" ", bg=c["panel"], fg=c["tenue"], font=self.f_expr, anchor="e")
        self.lbl_expr.pack(fill="x", padx=10, pady=(8, 0))
        self.lbl_display = tk.Label(pantalla, text="0", bg=c["panel"], fg=c["texto"], font=self.f_display, anchor="e")
        self.lbl_display.pack(fill="x", padx=10)
        self.lbl_info = tk.Label(pantalla, text=" ", bg=c["panel"], fg=c["tenue"], font=self.f_chico, anchor="e")
        self.lbl_info.pack(fill="x", padx=10, pady=(0, 8))

        # --- teclado ---
        teclado = tk.Frame(self.root, bg=c["fondo"])
        teclado.pack(padx=14, pady=4, fill="x")
        filas = [
            [("C", self.limpiar, "borrar"), ("⌫", self.retroceso, "tecla"), ("±", self.signo, "tecla"), ("÷", lambda: self.operar("DIV"), "operador")],
            [("7", None, "tecla"), ("8", None, "tecla"), ("9", None, "tecla"), ("×", lambda: self.operar("MUL"), "operador")],
            [("4", None, "tecla"), ("5", None, "tecla"), ("6", None, "tecla"), ("−", lambda: self.operar("SUB"), "operador")],
            [("1", None, "tecla"), ("2", None, "tecla"), ("3", None, "tecla"), ("+", lambda: self.operar("SUM"), "operador")],
            [("0", None, "tecla"), (".", self.punto, "tecla"), ("=", self.igual, "igual")],
        ]
        for r, fila in enumerate(filas):
            for col, (texto, accion, estilo) in enumerate(fila):
                accion = accion or (lambda d=texto: self.digito(d))
                b = tk.Button(teclado, text=texto, command=accion, font=self.f_tecla, bg=c[estilo],
                              fg=c["texto"], activebackground=c["operador"], activeforeground=c["texto"],
                              relief="flat", bd=0, height=1, cursor="hand2")
                span = 2 if texto == "=" else 1
                b.grid(row=r, column=col, columnspan=span, sticky="nsew", padx=3, pady=3, ipady=8)
        for col in range(4):
            teclado.columnconfigure(col, weight=1)

        # --- historial y bitácora ---
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill="both", expand=True, padx=14, pady=(8, 12))
        self.historial = tk.Listbox(notebook, bg=c["panel"], fg=c["texto"], font=self.f_chico,
                                    borderwidth=0, highlightthickness=0, activestyle="none")
        self.bitacora = tk.Text(notebook, bg=c["panel"], fg=c["tenue"], font=("Consolas", 8),
                                borderwidth=0, highlightthickness=0, wrap="none", height=10)
        notebook.add(self.historial, text="Historial")
        notebook.add(self.bitacora, text="Bitácora de mensajes")
        for tag, color in (("REQ", "#8ab4f8"), ("RES", c["ok"]), ("AJENA", c["tenue"]), ("DUPLIC", "#e9c46a"),
                           ("TIMEOUT", c["error"]), ("ERROR", c["error"]), ("CONN", c["ok"]), ("DISCONN", c["error"])):
            self.bitacora.tag_configure(tag, foreground=color)

        self.root.bind("<Key>", self._tecla)
        self.root.protocol("WM_DELETE_WINDOW", self.cerrar)

    # ---------- acciones del teclado ----------

    def _mostrar(self):
        self.lbl_display.config(text=self.actual)

    def digito(self, d):
        if self.esperando:
            return
        if self.nuevo_numero or self.actual == "0":
            self.actual = d
        elif len(self.actual) < 18:
            self.actual += d
        self.nuevo_numero = False
        self._mostrar()

    def punto(self):
        if self.esperando:
            return
        if self.nuevo_numero:
            self.actual, self.nuevo_numero = "0.", False
        elif "." not in self.actual:
            self.actual += "."
        self._mostrar()

    def signo(self):
        if self.esperando or self.actual in ("0", "Error"):
            return
        self.actual = self.actual[1:] if self.actual.startswith("-") else "-" + self.actual
        self._mostrar()

    def retroceso(self):
        if self.esperando or self.nuevo_numero:
            return
        self.actual = self.actual[:-1] or "0"
        if self.actual == "-":
            self.actual = "0"
        self._mostrar()

    def limpiar(self):
        self.actual, self.primero, self.servicio = "0", None, None
        self.esperando, self.nuevo_numero = None, True
        self.lbl_expr.config(text=" ")
        self.lbl_info.config(text=" ", fg=self.COLORES["tenue"])
        self._mostrar()

    def operar(self, servicio):
        if self.esperando:
            return
        try:
            self.primero = _parsear(self.actual)
        except ValueError:
            return
        self.servicio = servicio
        self.nuevo_numero = True
        self.lbl_expr.config(text=f"{_formatear(self.primero)} {cc.SERVICIOS[servicio][2]}")

    def igual(self):
        if self.esperando or self.servicio is None or self.primero is None:
            return
        try:
            segundo = _parsear(self.actual)
        except ValueError:
            return
        simbolo = cc.SERVICIOS[self.servicio][2]
        self.lbl_expr.config(text=f"{_formatear(self.primero)} {simbolo} {_formatear(segundo)} =")
        request_id = self.cliente.solicitar(self.servicio, self.primero, segundo)
        if request_id is None:
            self.lbl_info.config(text="Sin conexión con el Campo de Datos", fg=self.COLORES["error"])
            return
        self.esperando = request_id
        self.lbl_display.config(text="…")
        self.lbl_info.config(text=f"{cc.codigo_solicitud(self.servicio)} id={_corto(request_id)} enviado; "
                                  f"esperando respuesta…", fg=self.COLORES["tenue"])

    def _tecla(self, evento):
        mapa = {"+": "SUM", "-": "SUB", "*": "MUL", "x": "MUL", "/": "DIV"}
        if evento.char.isdigit():
            self.digito(evento.char)
        elif evento.char in ".,":
            self.punto()
        elif evento.char in mapa:
            self.operar(mapa[evento.char])
        elif evento.keysym in ("Return", "KP_Enter") or evento.char == "=":
            self.igual()
        elif evento.keysym == "BackSpace":
            self.retroceso()
        elif evento.keysym == "Escape":
            self.limpiar()

    # ---------- eventos de red (llegan por la cola) ----------

    def _procesar_cola(self):
        try:
            while True:
                tipo, info = self.cola.get_nowait()
                if tipo == "resultado":
                    self._mostrar_resultado(info)
                elif tipo == "timeout":
                    self._mostrar_timeout(info)
                elif tipo == "conexion":
                    n = info["nodos"]
                    self.lbl_estado.config(text=f"● conectado ({n} nodo{'s' if n != 1 else ''})" if n else "● sin conexión",
                                           fg=self.COLORES["ok"] if n else self.COLORES["error"])
                elif tipo == "log":
                    evento, linea = info
                    self.bitacora.insert("end", linea + "\n", evento.strip())
                    if int(self.bitacora.index("end-1c").split(".")[0]) > 2000:
                        self.bitacora.delete("1.0", "500.0")
                    self.bitacora.see("end")
        except queue.Empty:
            pass
        self.root.after(50, self._procesar_cola)

    def _mostrar_resultado(self, r):
        operacion = f"{_formatear(r['a'])} {r['simbolo']} {_formatear(r['b'])}"
        if r["error"]:
            salida, color = f"Error: {r['error']}", self.COLORES["error"]
        else:
            salida, color = _formatear(r["resultado"]), self.COLORES["ok"]
        self.historial.insert(0, f"{operacion} = {salida}   ← {r['servidor']} | ruta {r['ruta']} | {r['latencia_ms']} ms")
        if r["request_id"] != self.esperando:
            return
        self.esperando = None
        self.nuevo_numero = True
        self.servicio = None
        if r["error"]:
            self.actual, self.primero = "0", None
            self.lbl_display.config(text="Error")
        else:
            self.actual = _formatear(r["resultado"])
            self.primero = r["resultado"]
            self._mostrar()
        self.lbl_info.config(text=f"{cc.codigo_respuesta(r['servicio'])} de {r['servidor']} · ruta {r['ruta']} · "
                                  f"{r['latencia_ms']} ms" + (f" · {r['error']}" if r["error"] else ""), fg=color)

    def _mostrar_timeout(self, info):
        self.historial.insert(0, f"{_formatear(info['a'])} {info['simbolo']} {_formatear(info['b'])} = (sin respuesta)")
        if info["request_id"] == self.esperando:
            self.esperando = None
            self.actual, self.nuevo_numero = "0", True
            self.lbl_display.config(text="Sin respuesta")
            self.lbl_info.config(text=f"Ningún servidor {info['servicio']} respondió en "
                                      f"{self.cliente.timeout}s", fg=self.COLORES["error"])

    def ejecutar(self):
        self.cliente.iniciar()
        self.root.after(50, self._procesar_cola)
        self.root.mainloop()

    def cerrar(self):
        self.cliente.detener()
        registrar("FIN", f"Célula GUI {self.cliente.cell_id} cerrada")
        self.root.destroy()


# =====================================================================
# Modo sin ventana
# =====================================================================

_PATRON = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*([-+*/x×÷])\s*(-?\d+(?:\.\d+)?)\s*$")
_SIMBOLOS = {"+": "SUM", "-": "SUB", "*": "MUL", "x": "MUL", "×": "MUL", "/": "DIV", "÷": "DIV"}


def ejecutar_sin_gui(cell_id, nodos, cfg, operaciones, pausa):
    resultados = queue.Queue()
    cliente = ClienteCalculadora(cell_id, nodos, cfg, al_evento=lambda t, i: resultados.put((t, i)))
    cliente.iniciar()
    limite = time.monotonic() + 10
    while not cliente.acp.conectado() and time.monotonic() < limite:
        time.sleep(0.1)
    enviados = 0
    for texto in operaciones:
        m = _PATRON.match(texto)
        if not m:
            registrar("ERROR", f"Operación no reconocida: {texto!r} (ejemplo: 12.5*4)")
            continue
        a, op, b = _parsear(m.group(1)), m.group(2), _parsear(m.group(3))
        if cliente.solicitar(_SIMBOLOS[op], a, b):
            enviados += 1
        time.sleep(pausa)
    recibidos = 0
    fin = time.monotonic() + cfg["timeout_respuesta_s"] + 1
    while recibidos < enviados and time.monotonic() < fin:
        try:
            tipo, _ = resultados.get(timeout=0.2)
            if tipo in ("resultado", "timeout"):
                recibidos += 1
        except queue.Empty:
            pass
    if operaciones:
        time.sleep(1)  # deja ver posibles respuestas duplicadas en la bitácora
        cliente.detener()
        return
    try:  # sin operaciones: queda escuchando el broadcast
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        cliente.detener()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Célula cliente (GUI) de la calculadora ADS")
    comun.agregar_argumentos_comunes(parser)
    parser.add_argument("--sin-gui", action="store_true", help="ejecutar sin ventana (consola)")
    parser.add_argument("--operaciones", nargs="*", default=[], help='con --sin-gui: p. ej. "2+3" "10/0"')
    parser.add_argument("--pausa", type=float, default=0.5, help="segundos entre operaciones en --sin-gui")
    args = parser.parse_args(argv)

    cfg = comun.cargar_config(args.config)
    logger.configurar(comun.LOG_DIR, args.id)
    comun.titulo_consola(f"{args.id} - Bitacora GUI")

    if args.sin_gui:
        ejecutar_sin_gui(args.id, args.nodo, cfg, args.operaciones, args.pausa)
    else:
        VentanaCalculadora(args.id, args.nodo, cfg).ejecutar()


if __name__ == "__main__":
    main()
