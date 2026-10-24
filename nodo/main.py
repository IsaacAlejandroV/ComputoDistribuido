"""
Nodo del Campo de Datos (arquitectura ADS).

El mismo programa sirve para crear cualquier número de nodos: cada instancia
recibe su propio archivo de configuración.

    python src/main.py                         -> usa conf/config.json
    python src/main.py --config conf/nodo1.json
    python src/main.py --id NODO_5 --port 8075 --peers 127.0.0.1:8071

Los argumentos de línea de comandos tienen prioridad sobre el archivo.
"""
import argparse
import json
import os
import sys
import threading
import time
import uuid

# Forzamos UTF-8 en la consola de Windows (cp1252/850) para acentos y flechas.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import logger
from server import iniciar_servidor, set_identificador, registrar_mensaje_propio, ROLES_NODO
from client import (conectar_a_peer, configurar_identidad, direcciones_salientes, detener_cliente,
                    enviar_mensaje_a_todos, hay_conexiones)
from logger import registrar_evento
import peers
import discovery
import content_log
from topology_api import iniciar_api

PING_INTERVALO_SEGUNDOS = 2

if getattr(sys, "frozen", False):  # ejecutable generado con PyInstaller
    BASE = os.path.dirname(os.path.abspath(sys.executable))
else:
    BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.path.join(BASE, "conf", "config.json")


def hilo_ping_automatico(mi_node_id):
    """Latido entre nodos para comprobar que la malla sigue viva."""
    while True:
        time.sleep(PING_INTERVALO_SEGUNDOS)
        if hay_conexiones():
            msg_id = str(uuid.uuid4())
            registrar_mensaje_propio(msg_id)
            enviar_mensaje_a_todos({"type": "PING", "node_id": mi_node_id, "msg_id": msg_id},
                                   roles=ROLES_NODO)


def _entero_puerto(valor, nombre):
    if not isinstance(valor, int) or isinstance(valor, bool) or not 1 <= valor <= 65535:
        raise ValueError(f"{nombre} debe ser un entero entre 1 y 65535")
    return valor


def cargar_configuracion(ruta, args):
    config = {}
    if os.path.exists(ruta):
        with open(ruta, "r", encoding="utf-8") as file:
            config = json.load(file)
        if not isinstance(config, dict):
            raise ValueError("la configuración debe ser un objeto JSON")
    elif args.config:
        raise ValueError(f"no existe el archivo {ruta}")

    if args.id:
        config["node_id"] = args.id
    if args.host:
        config["host"] = args.host
    if args.port:
        config["port"] = args.port
    if args.api_port:
        config["api_port"] = args.api_port

    if not isinstance(config.get("node_id"), str) or not config["node_id"].strip():
        raise ValueError("node_id debe ser texto no vacío")
    config.setdefault("host", "0.0.0.0")
    _entero_puerto(config.get("port"), "port")
    config["api_port"] = _entero_puerto(config.get("api_port", config["port"] + 1000), "api_port")
    config.setdefault("api_host", "0.0.0.0")
    ttl = config.setdefault("ttl", 16)
    if not isinstance(ttl, int) or ttl < 1:
        raise ValueError("ttl debe ser un entero mayor que 0")
    config.setdefault("mostrar_ping", False)
    config.setdefault("guardar_descubiertos", True)

    # Lista de nodos a los que se conecta al iniciar. Se guarda en un archivo
    # propio de la instancia para que el descubrimiento (PEERS) lo actualice.
    conf_dir = os.path.dirname(os.path.abspath(ruta))
    nombre = config.get("connections_file", "connections.json")
    config["connections_file"] = nombre if os.path.isabs(nombre) else os.path.join(conf_dir, nombre)
    return config


def leer_conexiones(archivo):
    if not os.path.exists(archivo):
        return []
    try:
        with open(archivo, "r", encoding="utf-8") as f:
            lista = json.load(f)
        if not isinstance(lista, list):
            raise ValueError("debe contener una lista")
        return [p for p in lista if isinstance(p, str)]
    except (OSError, ValueError) as e:
        print(f"[!] Error leyendo {archivo}: {e}")
        return []


RETARDO_DESCUBRIMIENTO_S = 1.5


def _ya_conectado(endpoint):
    """¿Ya existe un enlace con ese nodo (lo marqué yo o él me marcó a mí)?"""
    return any(c["address"] == endpoint or c.get("endpoint") == endpoint for c in peers.topologia())


def conectar_descubierto(ip, puerto, mi_node_id):
    """
    Al descubrir un nodo por PEERS se espera un momento antes de marcarle: si
    mientras tanto él nos marca a nosotros (su HELLO trae su puerto de escucha),
    no se abre un segundo enlace. Así la malla completa queda con un solo
    enlace por par de nodos.
    """
    def intentar():
        endpoint = f"{ip}:{puerto}"
        if _ya_conectado(endpoint):
            registrar_evento(f"DESCUBRIMIENTO -> {endpoint} ya está enlazado; no se abre otro enlace")
            return
        conectar_a_peer(ip, puerto, mi_node_id)
    t = threading.Timer(RETARDO_DESCUBRIMIENTO_S, intentar)
    t.daemon = True
    t.start()


def imprimir_malla():
    conexiones = peers.topologia()
    nodos = [c for c in conexiones if c["role"] in ("node", "unknown")]
    celulas = [c for c in conexiones if c["role"] in ("cell", "app")]
    print(f"\n[*] Nodos vecinos ({len(nodos)}):")
    for c in nodos:
        print(f"    - {c['node_id'] or '?':<12} {c['address']:<22} ({c['connection']})")
    print(f"[*] Células conectadas ({len(celulas)}):")
    for c in celulas:
        servicio = f" [{c['service']}]" if c.get("service") else ""
        print(f"    - {c['node_id'] or '?':<12} {(c.get('cell_type') or '?') + servicio:<14} {c['address']}")
    print(f"[*] Nodos conocidos: {discovery.conocidos()}")


def main():
    parser = argparse.ArgumentParser(description="Nodo del Campo de Datos (ADS)")
    parser.add_argument("--config", help="archivo JSON de configuración de esta instancia")
    parser.add_argument("--id", help="identificador del nodo (sobrescribe node_id)")
    parser.add_argument("--host", help="interfaz de escucha (por defecto 0.0.0.0)")
    parser.add_argument("--port", type=int, help="puerto TCP de la malla")
    parser.add_argument("--api-port", type=int, help="puerto HTTP de la API de topología")
    parser.add_argument("--peers", nargs="*", default=[], help="nodos IP:PUERTO a los que conectarse")
    args = parser.parse_args()

    ruta = os.path.abspath(args.config) if args.config else CONFIG_FILE
    try:
        config = cargar_configuracion(ruta, args)
    except (OSError, ValueError) as e:
        sys.exit(f"[!] Error en la configuración ({ruta}): {e}")

    mi_node_id = config["node_id"]
    host, port = config["host"], config["port"]
    api_host, api_port = config["api_host"], config["api_port"]

    logger.configurar(mi_node_id)
    peers_iniciales = leer_conexiones(config["connections_file"]) + list(args.peers)

    set_identificador(mi_node_id, port, api_port, config["ttl"], config["mostrar_ping"])
    configurar_identidad(mi_node_id, port, api_port)
    discovery.configurar(
        config["connections_file"],
        f"127.0.0.1:{port}",
        lambda ip, puerto: conectar_descubierto(ip, puerto, mi_node_id),
        guardar=config["guardar_descubiertos"],
    )
    discovery.cargar(peers_iniciales)

    if os.name == "nt":
        os.system(f"title {mi_node_id} - Campo de Datos :{port}")
    print("=== Nodo del Campo de Datos (ADS) ===")
    print(f"[*] Nodo ID: {mi_node_id}")
    print(f"[*] Malla TCP: {host}:{port}  |  API: http://127.0.0.1:{api_port}/topology")
    print(f"[*] Nodos iniciales: {peers_iniciales or 'ninguno (esperando conexiones)'}")
    print("[*] Comandos: /malla  /celulas  /conectar IP:PUERTO  /ping  /enviar TEXTO  salir")
    print("=====================================\n")

    registrar_evento("=" * 50)
    registrar_evento(f"NODO INICIADO -> ID: {mi_node_id} | Escuchando en {host}:{port}")

    listo = threading.Event()
    threading.Thread(target=iniciar_servidor, args=(host, port, listo), daemon=True).start()
    threading.Thread(target=iniciar_api, args=(api_host, api_port, mi_node_id, port), daemon=True).start()
    listo.wait(3)

    for peer in peers_iniciales:
        try:
            p_ip, p_puerto = peer.rsplit(':', 1)
            conectar_a_peer(p_ip, p_puerto, mi_node_id)
        except ValueError:
            print(f"[!] Formato de peer inválido: {peer}. Usa IP:PUERTO")

    threading.Thread(target=hilo_ping_automatico, args=(mi_node_id,), daemon=True).start()

    try:
        while True:
            try:
                comando = input()
            except EOFError:
                # Sin consola interactiva (p. ej. lanzado en segundo plano): solo esperar.
                while True:
                    time.sleep(3600)
            partes = comando.strip().split()
            if not partes:
                continue
            cmd = partes[0].lower()

            if cmd in ['salir', 'exit', 'quit']:
                break
            elif cmd == '/conectar' and len(partes) == 2 and ":" in partes[1]:
                c_ip, c_puerto = partes[1].rsplit(':', 1)
                conectar_a_peer(c_ip, c_puerto, mi_node_id)
            elif cmd in ('/malla', '/peers', '/celulas'):
                imprimir_malla()
                print(f"[*] Conexiones salientes (yo marqué): {direcciones_salientes()}")
            elif cmd == '/ping':
                msg_id = str(uuid.uuid4())
                registrar_mensaje_propio(msg_id)
                enviar_mensaje_a_todos({"type": "PING", "node_id": mi_node_id, "msg_id": msg_id},
                                       roles=ROLES_NODO)
            elif cmd in ['/enviar', '/decir'] and len(partes) > 1:
                msg_id = str(uuid.uuid4())
                registrar_mensaje_propio(msg_id)
                enviar_mensaje_a_todos({"type": "TEXT", "node_id": mi_node_id, "msg_id": msg_id,
                                        "text": " ".join(partes[1:])}, roles=ROLES_NODO)
            elif cmd == '/contenido' and len(partes) >= 3:
                codigo = partes[1].upper()
                crudo = " ".join(partes[2:])
                try:
                    dato = json.loads(crudo)
                except ValueError:
                    dato = crudo
                msg_id = str(uuid.uuid4())
                registrar_mensaje_propio(msg_id)
                content_log.registrar(mi_node_id, codigo, dato, msg_id, None)
                n = enviar_mensaje_a_todos({"type": "CONTENT", "node_id": mi_node_id, "msg_id": msg_id,
                                            "content_code": codigo, "data": dato,
                                            "ttl": config["ttl"] - 1, "path": [mi_node_id]})
                registrar_evento(f"CONTENT PUBLICADO -> {codigo} = {dato!r} a {n} conexión(es)")
            else:
                print(f"[!] Comando no reconocido: {comando}")
    except KeyboardInterrupt:
        pass

    print("\n[!] Apagando nodo...")
    detener_cliente()
    registrar_evento("NODO APAGADO -> Proceso terminado por el usuario.")


if __name__ == "__main__":
    main()
