"""Utilidades compartidas por las células: rutas, configuración y arranque."""
import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):  # consolas de Windows (cp1252/850)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.path.join(BASE, "conf", "config.json")
LOG_DIR = os.path.join(BASE, "logs")

POR_DEFECTO = {
    "ttl": 16,                     # saltos máximos de un mensaje en la malla
    "retardo_por_salto_ms": 300,   # servidor: espera extra por cada nodo de distancia
    "ventana_desempate_ms": 120,   # servidor: dispersión determinista entre servidores
    "timeout_respuesta_s": 5,      # GUI: tiempo máximo de espera de una respuesta
    "mostrar_ignorados": True,     # registrar en bitácora lo que llega pero no interesa
}


def cargar_config(ruta=None):
    ruta = os.path.abspath(ruta) if ruta else CONFIG_FILE
    cfg = dict(POR_DEFECTO)
    if os.path.exists(ruta):
        try:
            with open(ruta, "r", encoding="utf-8") as f:
                datos = json.load(f)
        except ValueError:
            sys.exit(f"[!] {ruta} no es un JSON válido.")
        if not isinstance(datos, dict):
            sys.exit("[!] La configuración debe ser un objeto JSON.")
        cfg.update(datos)
    for clave in ("ttl", "retardo_por_salto_ms", "ventana_desempate_ms", "timeout_respuesta_s"):
        if not isinstance(cfg[clave], (int, float)) or isinstance(cfg[clave], bool) or cfg[clave] < 0:
            sys.exit(f"[!] '{clave}' debe ser un número no negativo.")
    cfg["ttl"] = max(1, int(cfg["ttl"]))
    return cfg


def agregar_argumentos_comunes(parser):
    parser.add_argument("--id", required=True, help="identificador único de la célula (p. ej. GUI_N1)")
    parser.add_argument("--nodo", nargs="+", required=True, metavar="IP:PUERTO",
                        help="nodo(s) del Campo de Datos al que se conecta la célula")
    parser.add_argument("--config", help="archivo de parámetros (por defecto conf/config.json)")


def titulo_consola(texto):
    if os.name == "nt":
        os.system(f"title {texto}")
