"""
preproceso.py
Escalado de zonas, anonimizacion y validacion de escena — GondHawk.

Resuelve tres problemas que aparecieron al conectar el backend con el frontend:

1. ESCALADO DE ZONAS
   `zonas.json` esta dibujado sobre vtest.avi (768x576). El pipeline lo usaba
   tal cual con cualquier video subido, asi que en un video 1080p las cinco
   zonas quedaban amontonadas en la esquina superior izquierda, cubriendo el
   9% del frame. El heatmap se calculaba bien sobre el video real, pero el
   overlay de zonas era siempre el mismo dibujo: por eso parecia una plantilla
   fija. `escalar_zonas()` reproyecta los poligonos a la resolucion real.

2. ANONIMIZACION DE ROSTROS
   Si el video de entrada muestra caras, el frame de fondo del heatmap y el
   video anotado las conservan. `AnonimizadorRostros` difumina la region de
   cabeza de cada persona detectada antes de que el frame se guarde o se
   muestre. No usa reconocimiento facial: no hace falta saber DONDE esta la
   cara con precision biometrica, basta con tapar el tercio superior del bbox
   de la persona, que es justamente lo que exige la Ley 1581.

3. VALIDACION DE ESCENA
   El sistema debe rechazar videos que no sean de una superficie comercial.
   `evaluar_escena_retail()` da un puntaje heuristico a partir de senales
   observables sin entrenar nada: proporcion de la imagen ocupada por
   estructuras verticales repetidas (estanteria), saturacion de color en las
   bandas altas del frame (producto empacado) y densidad de bordes horizontales
   regulares (entrepanos). No es un clasificador entrenado y no pretende serlo:
   es un filtro de cordura que evita procesar 10 minutos de un video de
   paisaje.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np


# ── 1. Escalado de zonas ────────────────────────────────────────────────────


def escalar_zonas(
    zonas_raw: dict[str, Any],
    ancho_destino: int,
    alto_destino: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Reproyecta los poligonos de zonas a la resolucion real del video.

    Devuelve (zonas_escaladas, info) donde `info` documenta el factor aplicado
    para que quede registrado en las salidas: si alguien revisa el heatmap y
    las zonas no cuadran con los estantes, tiene que poder ver que hubo un
    escalado y de cuanto.

    El escalado es proporcional e independiente por eje. Eso funciona cuando el
    video nuevo encuadra la misma escena; si es otra tienda con otro layout, el
    escalado no puede inventar donde estan las gondolas y hay que redefinir las
    zonas con `mapas_de_calor/src/zone_definer.py`. La bandera `confiable` en
    `info` marca ese caso: cuando la relacion de aspecto cambia mas de un 10%,
    las zonas escaladas son una aproximacion, no una definicion valida.
    """
    ancho_origen = int(zonas_raw.get("frame_width") or ancho_destino)
    alto_origen = int(zonas_raw.get("frame_height") or alto_destino)

    if ancho_origen <= 0 or alto_origen <= 0:
        raise ValueError(
            f"zonas.json declara una resolucion invalida: {ancho_origen}x{alto_origen}"
        )

    fx = ancho_destino / ancho_origen
    fy = alto_destino / alto_origen

    aspecto_origen = ancho_origen / alto_origen
    aspecto_destino = ancho_destino / alto_destino
    desvio_aspecto = abs(aspecto_destino - aspecto_origen) / aspecto_origen

    escaladas = dict(zonas_raw)
    escaladas["frame_width"] = ancho_destino
    escaladas["frame_height"] = alto_destino
    escaladas["zonas"] = [
        {
            **zona,
            "poligono": [
                [
                    min(round(px * fx), ancho_destino - 1),
                    min(round(py * fy), alto_destino - 1),
                ]
                for px, py in zona["poligono"]
            ],
        }
        for zona in zonas_raw.get("zonas", [])
    ]

    info = {
        "resolucion_origen": [ancho_origen, alto_origen],
        "resolucion_destino": [ancho_destino, alto_destino],
        "factor_x": round(fx, 4),
        "factor_y": round(fy, 4),
        "escalado_aplicado": fx != 1.0 or fy != 1.0,
        "desvio_aspecto": round(desvio_aspecto, 4),
        "confiable": desvio_aspecto <= 0.10,
    }

    if not info["confiable"]:
        info["advertencia"] = (
            "La relacion de aspecto del video difiere de aquella para la que se "
            "definieron las zonas. Las zonas escaladas son aproximadas: conviene "
            "redefinirlas con mapas_de_calor/src/zone_definer.py."
        )

    return escaladas, info


# ── 2. Anonimizacion ────────────────────────────────────────────────────────


@dataclass
class ConfigAnonimizacion:
    """Parametros del difuminado de rostros."""

    activo: bool = True
    proporcion_cabeza: float = 0.30   # tercio superior del bbox de la persona
    margen: float = 0.12              # ensancha la region para cubrir el pelo
    fuerza: int = 0                   # 0 = automatico segun el tamano del bbox
    modo: str = "blur"                # "blur" | "pixelado" | "solido"


class AnonimizadorRostros:
    """
    Difumina la region de cabeza de las personas detectadas en un frame.

    Trabaja sobre los bboxes que YA entrega el detector de personas, asi que no
    agrega un segundo modelo al pipeline ni cuesta tiempo de inferencia extra.
    Esto es deliberado: un detector de rostros tendria que LOCALIZAR caras para
    poder taparlas, y ese calculo intermedio es justamente el dato biometrico
    que el reto excluye por diseno. Tapando el tercio superior del cuerpo se
    consigue el mismo efecto sin computar nunca una cara.
    """

    def __init__(self, config: ConfigAnonimizacion | None = None):
        self.config = config or ConfigAnonimizacion()
        self.rostros_cubiertos = 0

    def aplicar(
        self,
        frame: np.ndarray,
        detecciones: list[dict[str, Any]],
    ) -> np.ndarray:
        """Devuelve una copia del frame con las cabezas difuminadas."""
        if not self.config.activo or frame is None or not len(detecciones):
            return frame

        salida = frame.copy()
        alto, ancho = salida.shape[:2]

        for det in detecciones:
            bbox = det.get("bbox")
            if not bbox or len(bbox) != 4:
                continue

            x1, y1, x2, y2 = (float(v) for v in bbox)
            ancho_persona = x2 - x1
            alto_persona = y2 - y1
            if ancho_persona <= 0 or alto_persona <= 0:
                continue

            margen = ancho_persona * self.config.margen
            rx1 = max(0, int(x1 - margen))
            rx2 = min(ancho, int(x2 + margen))

            # Una persona agachada (tomando producto de una repisa baja, el
            # evento de negocio central del sistema) tiene un bbox más ancho
            # que alto: ahí la cabeza no está en el "tercio superior" del
            # bbox de pie, sino mucho más abajo proporcionalmente. Se amplía
            # la proporción cubierta cuando el bbox es "achatado" para no
            # dejar la cabeza fuera de la región difuminada.
            proporcion = self.config.proporcion_cabeza
            if ancho_persona > alto_persona:
                proporcion = min(0.7, proporcion * (ancho_persona / alto_persona))

            ry1 = max(0, int(y1 - alto_persona * self.config.margen))
            ry2 = min(alto, int(y1 + alto_persona * proporcion))

            if rx2 - rx1 < 2 or ry2 - ry1 < 2:
                continue

            region = salida[ry1:ry2, rx1:rx2]
            salida[ry1:ry2, rx1:rx2] = self._ofuscar(region)
            self.rostros_cubiertos += 1

        return salida

    def _ofuscar(self, region: np.ndarray) -> np.ndarray:
        alto, ancho = region.shape[:2]

        if self.config.modo == "solido":
            return np.zeros_like(region)

        if self.config.modo == "pixelado":
            # Reducir a ~8 px de lado y volver a ampliar: destruye el detalle
            # de forma irreversible, a diferencia de un blur suave.
            pequeno = cv2.resize(
                region, (max(1, ancho // 12), max(1, alto // 12)),
                interpolation=cv2.INTER_LINEAR,
            )
            return cv2.resize(pequeno, (ancho, alto), interpolation=cv2.INTER_NEAREST)

        # blur gaussiano con kernel proporcional al tamano de la region, para
        # que una persona en primer plano quede tan tapada como una de fondo
        k = self.config.fuerza or max(9, (min(alto, ancho) // 2) | 1)
        if k % 2 == 0:
            k += 1
        return cv2.GaussianBlur(region, (k, k), 0)


# ── 3. Validacion de escena ─────────────────────────────────────────────────


@dataclass
class ResultadoEscena:
    es_retail: bool
    puntaje: float
    senales: dict[str, float] = field(default_factory=dict)
    motivo: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "es_retail": self.es_retail,
            "puntaje": round(self.puntaje, 3),
            "senales": {k: round(v, 3) for k, v in self.senales.items()},
            "motivo": self.motivo,
        }


def evaluar_escena_retail(
    frames: list[np.ndarray],
    umbral: float = 0.45,
) -> ResultadoEscena:
    """
    Estima si los frames corresponden a una superficie comercial.

    Tres senales, todas calculadas sobre la imagen sin ningun modelo entrenado:

    - `estructura_vertical`: densidad de bordes verticales largos y regulares.
      Las estanterias los producen; un parque o una oficina, no.
    - `lineas_horizontales`: bordes horizontales repetidos a intervalos
      parecidos, que es la firma de los entrepanos de una gondola.
    - `saturacion_producto`: fraccion de pixeles muy saturados en la mitad
      superior del frame. El producto empacado es de colores fuertes; el
      pavimento, la vegetacion y la ropa, no tanto.

    Es un filtro de cordura para rechazar videos claramente fuera de tema, no
    un clasificador de escenas. Hay que documentarlo asi: en la sustentacion,
    presentarlo como IA entrenada seria facil de desmontar con una pregunta.
    """
    if not frames:
        # No poder muestrear no es evidencia de que el video sea invalido: el
        # pipeline lo abrira igual mas adelante. Se deja pasar con aviso, para
        # no bloquear un video legitimo por una limitacion del muestreo.
        return ResultadoEscena(
            True, 0.0,
            motivo=(
                "No se pudieron muestrear frames para verificar la escena; "
                "se continua sin verificar."
            ),
        )

    verticales: list[float] = []
    horizontales: list[float] = []
    saturaciones: list[float] = []

    for frame in frames:
        if frame is None or frame.size == 0:
            continue

        gris = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        alto, ancho = gris.shape[:2]

        sobel_x = np.abs(cv2.Sobel(gris, cv2.CV_32F, 1, 0, ksize=3))
        sobel_y = np.abs(cv2.Sobel(gris, cv2.CV_32F, 0, 1, ksize=3))

        # Bordes verticales fuertes, promediados por columna: una estanteria
        # produce columnas completas con borde, no puntos sueltos.
        col_score = (sobel_x > 60).mean(axis=0)
        verticales.append(float((col_score > 0.25).mean()))

        fila_score = (sobel_y > 60).mean(axis=1)
        horizontales.append(float((fila_score > 0.25).mean()))

        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        mitad_superior = hsv[: alto // 2, :, 1]
        saturaciones.append(float((mitad_superior > 90).mean()))

    if not verticales:
        return ResultadoEscena(
            True, 0.0,
            motivo="Los frames muestreados estan vacios; se continua sin verificar.",
        )

    senales = {
        "estructura_vertical": float(np.mean(verticales)),
        "lineas_horizontales": float(np.mean(horizontales)),
        "saturacion_producto": float(np.mean(saturaciones)),
    }

    puntaje = (
        0.45 * min(senales["estructura_vertical"] / 0.35, 1.0)
        + 0.30 * min(senales["lineas_horizontales"] / 0.30, 1.0)
        + 0.25 * min(senales["saturacion_producto"] / 0.25, 1.0)
    )

    es_retail = puntaje >= umbral
    motivo = (
        "La escena presenta estructura de estanteria y producto visible."
        if es_retail
        else (
            "La escena no presenta las senales tipicas de una superficie "
            "comercial (estanteria vertical, entrepanos y producto empacado). "
            "Si el video si es de una tienda, baja el umbral con --umbral-escena "
            "o desactiva la verificacion con --sin-verificar-escena."
        )
    )

    return ResultadoEscena(es_retail, puntaje, senales, motivo)


def muestrear_frames(video_path: str, n: int = 12) -> list[np.ndarray]:
    """
    Toma n frames repartidos a lo largo del video, sin leerlo entero.

    Estrategia en dos pasos, y el segundo no es opcional: en muchos AVI y en
    videos con codecs sin indice de busqueda, `cap.set(CAP_PROP_POS_FRAMES, k)`
    falla en silencio — no lanza error, simplemente el `read()` siguiente
    devuelve False. Si solo se intenta el salto, se termina con cero frames en
    un video perfectamente legible.

    1. Salto directo a posiciones repartidas (rapido, sirve para mp4/mkv).
    2. Si el salto no produjo frames, lectura secuencial tomando 1 de cada k.
    """
    frames = _muestrear_por_salto(video_path, n)
    if frames:
        return frames
    return _muestrear_secuencial(video_path, n)


def _muestrear_por_salto(video_path: str, n: int) -> list[np.ndarray]:
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return []

    frames: list[np.ndarray] = []
    try:
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
        if total <= 0:
            return []
        for i in range(n):
            if not cap.set(cv2.CAP_PROP_POS_FRAMES, int(i * total / n)):
                return []
            ok, frame = cap.read()
            if ok and frame is not None and frame.size:
                frames.append(frame)
    finally:
        cap.release()

    return frames


def _muestrear_secuencial(video_path: str, n: int, tope: int = 900) -> list[np.ndarray]:
    """Lee el video de corrido y se queda con n frames repartidos."""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return []

    frames: list[np.ndarray] = []
    try:
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
        # Si no se conoce la duracion, se toma 1 de cada 10 hasta llenar n.
        paso = max(1, total // n) if total > 0 else 10

        leidos = 0
        while len(frames) < n and leidos < tope:
            ok, frame = cap.read()
            if not ok:
                break
            if leidos % paso == 0 and frame is not None and frame.size:
                frames.append(frame)
            leidos += 1
    finally:
        cap.release()

    return frames
