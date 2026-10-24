import random
import threading

import content_codes as cc
from logger import registrar


class SensorTemperaturaASM:
    """
    Application Software Module: piensa y actúa.
    Simula un sensor de temperatura. No sabe nada de redes ni de nodos: solo
    devuelve contenido para que el ACP lo publique y recibe lo que el ACP le entrega.
    Si el aire acondicionado está encendido, la temperatura baja en vez de subir.
    """

    def __init__(self, temperatura_inicial=26.0):
        self.temperatura = temperatura_inicial
        self.aire = "OFF"
        self._lock = threading.Lock()

    def generar(self):
        """Toma una lectura y devuelve la lista de (content_code, dato) a publicar."""
        with self._lock:
            deriva = random.uniform(-0.2, 0.5)
            if self.aire == "ON":
                deriva -= 1.0
            self.temperatura = min(40.0, max(15.0, self.temperatura + deriva))
            return [(cc.TEMPERATURA, round(self.temperatura, 1))]

    def procesar(self, mensaje):
        """Recibe únicamente lo que el ACP consideró relevante."""
        if mensaje["content_code"] == cc.ESTADO_AIRE and mensaje["data"] in ("ON", "OFF"):
            with self._lock:
                cambio = mensaje["data"] != self.aire
                self.aire = mensaje["data"]
            if cambio:
                efecto = "bajará" if self.aire == "ON" else "volverá a subir"
                registrar("ASM", f"El aire quedó en {self.aire}: la temperatura {efecto}")
        return None
