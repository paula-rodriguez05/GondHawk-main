"""
reach_detector.py
Deteccion de "alcance" (reach) — Modulo 1, GondHawk.

Un *alcance* es el gesto de estirar el brazo hacia el estante. Es la senal
fisica primaria a partir de la cual se derivan los eventos de pick-up y
put-back. Este archivo aisla esa deteccion detras de una interfaz comun para
que la maquina de estados no dependa de como se obtiene la senal.

Dos estrategias:

1. GeometricReachDetector (por defecto, disponible HOY)
   Solo necesita el bbox que ya entrega el modulo 3. Cuando una persona
   extiende el brazo hacia la gondola, su silueta se ensancha sin que cambie
   su altura. La senal es la relacion de aspecto `w/h`, que es invariante a la
   escala: si la persona se aleja de la camara, w y h se reducen juntos y el
   aspecto no se mueve. Se compara contra una linea base propia de cada track
   (mediana movil de sus frames "en reposo"), asi que no importa si la persona
   es ancha, lleva mochila o esta de perfil.

2. PoseReachDetector (mejor exactitud, requiere keypoints)
   Si el modulo 2/3 llega a entregar `keypoints` por track (YOLOv8-pose, como
   sugiere el reto), usa la extension real de la muneca respecto al hombro,
   normalizada por la altura del torso. La maquina de estados no cambia: solo
   se le inyecta el otro detector.

Ambos aplican histeresis (umbral de entrada > umbral de salida) para no
generar eventos duplicados por el ruido de un frame suelto, y validan la
duracion del gesto para descartar tanto parpadeos del detector como cajas
que se fusionaron con las de otra persona.

Privacidad: ninguna estrategia guarda recortes de imagen ni descriptores
biometricos. Se trabaja sobre numeros geometricos ya anonimos.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from statistics import median
from typing import Any


@dataclass
class ReachConfig:
    """Parametros de la deteccion de alcance."""

    # Histeresis sobre la expansion relativa del aspecto (w/h) del bbox.
    umbral_entrada: float = 0.03   # antes 0.18
    umbral_salida: float = 0.015    # antes 0.08

    ventana_baseline: int = 20     # frames de reposo usados para la mediana
    min_muestras_baseline: int = 5  # antes de esto no se declara ningun alcance

    min_duracion_ms: float = 150.0    # gesto mas corto = ruido del detector
    max_duracion_ms: float = 8000.0   # gesto mas largo = bbox fusionado / error
    min_frames: int = 1

    # Pose (solo PoseReachDetector): extension muneca-hombro normalizada por
    # la altura del torso.
    umbral_pose_entrada: float = 0.55
    umbral_pose_salida: float = 0.35


@dataclass
class Reach:
    """Un gesto de alcance ya cerrado."""

    track_id: str
    inicio_ms: float
    fin_ms: float
    pico: float          # maxima expansion relativa observada
    frames: int
    valido: bool = True
    motivo_descarte: str | None = None

    @property
    def duracion_ms(self) -> float:
        return self.fin_ms - self.inicio_ms

    @property
    def confianza(self) -> float:
        """
        Confianza heuristica en [0, 1]: cuanto mas marcado el gesto y mas
        frames lo sostienen, mas confiable. Es una senal para el tablero y
        para filtrar eventos dudosos, no una probabilidad calibrada.
        """
        if not self.valido:
            return 0.0
        c_pico = min(self.pico / 0.45, 1.0)
        c_frames = min(self.frames / 6.0, 1.0)
        return round(0.6 * c_pico + 0.4 * c_frames, 3)


@dataclass
class _EstadoTrack:
    baseline: deque = field(default_factory=deque)
    activo: bool = False
    inicio_ms: float = 0.0
    ultimo_ms: float = 0.0
    pico: float = 0.0
    frames: int = 0


class BaseReachDetector:
    """Interfaz comun. `update` devuelve un Reach solo al cerrarse el gesto."""

    nombre = "base"

    def __init__(self, config: ReachConfig | None = None):
        self.config = config or ReachConfig()
        self._tracks: dict[str, _EstadoTrack] = {}

    # -- API publica -------------------------------------------------------

    def update(
        self,
        track_id: str,
        track: dict[str, Any],
        timestamp_ms: float,
    ) -> Reach | None:
        senal = self._senal(track_id, track)
        if senal is None:
            return None
        return self._procesar_senal(track_id, senal, timestamp_ms)

    def cerrar(self, track_id: str, timestamp_ms: float) -> Reach | None:
        """
        Cierra un alcance que quedo abierto porque la persona salio de la zona
        o termino el video. Un gesto sin cierre observado se marca invalido:
        no sabemos si termino de tomar el producto.
        """
        estado = self._tracks.get(track_id)
        if estado is None or not estado.activo:
            return None

        reach = self._construir(track_id, estado, timestamp_ms)
        self._reset(estado)
        if reach.valido:
            reach.valido = False
            reach.motivo_descarte = "alcance sin cierre observado"
        return reach

    def olvidar(self, track_id: str) -> None:
        """Libera memoria de un track que ya no aparece (privacidad + RAM)."""
        self._tracks.pop(track_id, None)

    # -- Implementacion compartida ----------------------------------------

    def _senal(self, track_id: str, track: dict[str, Any]) -> float | None:
        raise NotImplementedError

    def _procesar_senal(
        self,
        track_id: str,
        senal: float,
        timestamp_ms: float,
    ) -> Reach | None:
        estado = self._tracks.setdefault(track_id, _EstadoTrack())
        cfg = self.config

        if len(estado.baseline) < cfg.min_muestras_baseline:
            estado.baseline.append(senal)
            if len(estado.baseline) > cfg.ventana_baseline:
                estado.baseline.popleft()
            return None

        base = median(estado.baseline)
        expansion = (senal - base) / base if base > 0 else 0.0

        if not estado.activo:
            if expansion >= self._umbral_entrada:
                estado.activo = True
                estado.inicio_ms = timestamp_ms
                estado.pico = expansion
                estado.frames = 1
                estado.ultimo_ms = timestamp_ms
            else:
                # Solo se alimenta la linea base con frames en reposo, para que
                # un alcance largo no "normalice" su propia senal.
                estado.baseline.append(senal)
                if len(estado.baseline) > cfg.ventana_baseline:
                    estado.baseline.popleft()
            return None

        estado.frames += 1
        estado.ultimo_ms = timestamp_ms
        estado.pico = max(estado.pico, expansion)

        if expansion <= self._umbral_salida:
            reach = self._construir(track_id, estado, timestamp_ms)
            self._reset(estado)
            estado.baseline.append(senal)
            if len(estado.baseline) > cfg.ventana_baseline:
                estado.baseline.popleft()
            return reach

        return None

    def _construir(
        self,
        track_id: str,
        estado: _EstadoTrack,
        fin_ms: float,
    ) -> Reach:
        cfg = self.config
        reach = Reach(
            track_id=track_id,
            inicio_ms=estado.inicio_ms,
            fin_ms=fin_ms,
            pico=round(estado.pico, 4),
            frames=estado.frames,
        )

        if reach.duracion_ms < cfg.min_duracion_ms:
            reach.valido = False
            reach.motivo_descarte = (
                f"duracion {reach.duracion_ms:.0f} ms < minimo {cfg.min_duracion_ms:.0f} ms"
            )
        elif reach.duracion_ms > cfg.max_duracion_ms:
            reach.valido = False
            reach.motivo_descarte = (
                f"duracion {reach.duracion_ms:.0f} ms > maximo {cfg.max_duracion_ms:.0f} ms "
                "(posible fusion de bboxes)"
            )
        elif reach.frames < cfg.min_frames:
            reach.valido = False
            reach.motivo_descarte = f"solo {reach.frames} frame(s) sostenidos"

        return reach

    @staticmethod
    def _reset(estado: _EstadoTrack) -> None:
        estado.activo = False
        estado.inicio_ms = 0.0
        estado.pico = 0.0
        estado.frames = 0

    @property
    def _umbral_entrada(self) -> float:
        return self.config.umbral_entrada

    @property
    def _umbral_salida(self) -> float:
        return self.config.umbral_salida


class GeometricReachDetector(BaseReachDetector):
    """Alcance a partir de la relacion de aspecto del bbox. Sin dependencias."""

    nombre = "geometrico"

    def _senal(self, track_id: str, track: dict[str, Any]) -> float | None:
        bbox = track.get("bbox")
        if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
            return None
        try:
            x1, y1, x2, y2 = (float(v) for v in bbox)
        except (TypeError, ValueError):
            return None

        ancho = x2 - x1
        alto = y2 - y1
        if ancho <= 0 or alto <= 0:
            return None

        return ancho / alto  # invariante a la escala/distancia a la camara


class PoseReachDetector(BaseReachDetector):
    """
    Alcance a partir de keypoints (formato COCO de YOLOv8-pose).

    Espera `track["keypoints"]` como lista de [x, y, conf] con indices COCO:
    5 hombro izq, 6 hombro der, 9 muneca izq, 10 muneca der, 11/12 caderas.
    Si el track no trae keypoints utiles, retorna None y la maquina de estados
    simplemente no ve senal para ese frame.
    """

    nombre = "pose"

    IZQ_HOMBRO, DER_HOMBRO = 5, 6
    IZQ_MUNECA, DER_MUNECA = 9, 10
    IZQ_CADERA, DER_CADERA = 11, 12

    def __init__(self, config: ReachConfig | None = None, min_conf: float = 0.3):
        super().__init__(config)
        self.min_conf = min_conf

    def _punto(self, kps: list, idx: int) -> tuple[float, float] | None:
        if idx >= len(kps):
            return None
        kp = kps[idx]
        if not isinstance(kp, (list, tuple)) or len(kp) < 2:
            return None
        if len(kp) >= 3 and float(kp[2]) < self.min_conf:
            return None
        return (float(kp[0]), float(kp[1]))

    def _senal(self, track_id: str, track: dict[str, Any]) -> float | None:
        kps = track.get("keypoints")
        if not isinstance(kps, (list, tuple)):
            return None

        hombros = [
            p
            for p in (
                self._punto(kps, self.IZQ_HOMBRO),
                self._punto(kps, self.DER_HOMBRO),
            )
            if p
        ]
        caderas = [
            p
            for p in (
                self._punto(kps, self.IZQ_CADERA),
                self._punto(kps, self.DER_CADERA),
            )
            if p
        ]
        if not hombros or not caderas:
            return None

        hombro_y = sum(p[1] for p in hombros) / len(hombros)
        cadera_y = sum(p[1] for p in caderas) / len(caderas)
        torso = abs(cadera_y - hombro_y)
        if torso <= 1e-6:
            return None

        extension = 0.0
        for h_idx, m_idx in (
            (self.IZQ_HOMBRO, self.IZQ_MUNECA),
            (self.DER_HOMBRO, self.DER_MUNECA),
        ):
            hombro = self._punto(kps, h_idx)
            muneca = self._punto(kps, m_idx)
            if hombro and muneca:
                dx = muneca[0] - hombro[0]
                dy = muneca[1] - hombro[1]
                extension = max(extension, (dx * dx + dy * dy) ** 0.5 / torso)

        return extension or None

    @property
    def _umbral_entrada(self) -> float:
        return self.config.umbral_pose_entrada

    @property
    def _umbral_salida(self) -> float:
        return self.config.umbral_pose_salida


def crear_detector(modo: str, config: ReachConfig | None = None) -> BaseReachDetector:
    """Fabrica: 'geometrico' (default) | 'pose'."""
    modo = (modo or "geometrico").lower()
    if modo in ("geometrico", "geometric", "bbox"):
        return GeometricReachDetector(config)
    if modo == "pose":
        return PoseReachDetector(config)
    raise ValueError(f"Modo de deteccion de alcance desconocido: {modo}")
