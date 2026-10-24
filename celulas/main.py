"""
Lanzador de células de la calculadora ADS.

    python src/main.py gui      --id GUI_N1     --nodo 127.0.0.1:8071
    python src/main.py servidor --id SRV_SUM_N1 --nodo 127.0.0.1:8071 --servicio SUM

Equivale a ejecutar directamente src/celula_gui.py o src/celula_servidor.py.
"""
import sys

USO = "Uso: python src/main.py (gui|servidor) --id ID --nodo IP:PUERTO [--servicio SUM|SUB|MUL|DIV]"

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1].lower() not in ("gui", "cliente", "servidor", "server"):
        sys.exit(USO)
    tipo, resto = sys.argv[1].lower(), sys.argv[2:]
    if tipo in ("gui", "cliente"):
        import celula_gui
        celula_gui.main(resto)
    else:
        import celula_servidor
        celula_servidor.main(resto)
