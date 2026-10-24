import datetime
import os
import re
import sys
import threading

if getattr(sys, "frozen", False):  # ejecutable de PyInstaller: logs junto al .exe
    BASE = os.path.dirname(os.path.abspath(sys.executable))
else:
    BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(BASE, "logs")
BITACORA_FILE = os.path.join(LOG_DIR, "bitacora.log")
_lock = threading.Lock()


def configurar(node_id):
    """
    Usa un archivo de bitácora por instancia (logs/bitacora_<node_id>.log),
    para poder ejecutar varios nodos desde la misma carpeta sin mezclar eventos.
    """
    global BITACORA_FILE
    seguro = re.sub(r"[^A-Za-z0-9_.-]", "_", node_id) or "nodo"
    BITACORA_FILE = os.path.join(LOG_DIR, f"bitacora_{seguro}.log")


def registrar_evento(evento):
    """
    Muestra el evento en consola con hora exacta (con milisegundos, para poder
    seguir el recorrido de un mensaje entre nodos) y lo añade al archivo de
    bitácora de este nodo.
    """
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    linea = f"[{timestamp}] {evento}"

    with _lock:
        print(linea, flush=True)
        os.makedirs(LOG_DIR, exist_ok=True)
        try:
            with open(BITACORA_FILE, "a", encoding="utf-8") as f:
                f.write(linea + "\n")
        except OSError as e:
            print(f"[!] Error escribiendo en bitácora: {e}")
