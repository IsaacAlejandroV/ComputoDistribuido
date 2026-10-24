import datetime
import os
import re
import threading

_lock = threading.Lock()
_archivo = None
_oyentes = []  # funciones que reciben cada línea (la GUI las muestra en pantalla)


def configurar(directorio_logs, celula_id="celula"):
    """Una bitácora por célula: logs/bitacora_<id>.log"""
    global _archivo
    os.makedirs(directorio_logs, exist_ok=True)
    seguro = re.sub(r"[^A-Za-z0-9_.-]", "_", celula_id) or "celula"
    _archivo = os.path.join(directorio_logs, f"bitacora_{seguro}.log")


def agregar_oyente(funcion):
    _oyentes.append(funcion)


def registrar(evento, detalle=""):
    """
    Eventos: INICIO, CONN, DISCONN, TX, RX, IGNORE, DROP, REQ, RES, ESPERA,
    SUPRIME, DUPLIC, AJENA, TIMEOUT, WARN, ERROR, FIN.
    Se imprime en consola y se guarda en la bitácora de la célula.
    """
    hora = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    linea = f"[{hora}] {evento:<7} | {detalle}"
    with _lock:
        print(linea, flush=True)
        if _archivo:
            try:
                with open(_archivo, "a", encoding="utf-8") as f:
                    f.write(linea + "\n")
            except OSError as e:
                print(f"[!] No se pudo escribir la bitácora: {e}", flush=True)
    for oyente in list(_oyentes):
        try:
            oyente(evento, linea)
        except Exception:
            pass
