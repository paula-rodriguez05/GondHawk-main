"""
state_machine.py
Maquina de estados de interaccion por persona — Modulo 1, GondHawk.

Es el corazon del modulo: convierte trayectorias anonimas (modulo 3) en el
embudo fisico de compra que pide el reto:

    pasa de largo -> se detiene -> toma el producto -> lo devuelve / se lo lleva

Cada `track_id` tiene su propia maquina. Un *episodio* es una visita continua
de una persona a una zona; si la persona sale y vuelve, son dos episodios.

    FUERA ──(centroide entra a gondola)──> TRANSITO
    TRANSITO ──(dwell >= min_dwell)──> DETENIDO            [evento: approach]
    TRANSITO ──(sale antes del umbral)──> FUERA            [evento: pass_by]
    DETENIDO ──(alcance valido)──> CON_PRODUCTO            [evento: pickup]
    CON_PRODUCTO ──(segundo alcance)──> DETENIDO           [evento: return]
    CON_PRODUCTO ──(sale de la zona)──> FUERA              [evento: takeaway]
    DETENIDO ──(sale de la zona)──> FUERA                  [sin evento extra]

Supuesto central, y hay que decirlo explicito porque es la limitacion del
prototipo: **no reconocemos el producto**. Un alcance no dice si la mano salio
llena o vacia. La regla que usamos es de secuencia, no de vision:

  - el primer alcance de un episodio se interpreta como pick-up;
  - un alcance posterior en la misma zona, en el mismo episodio, se interpreta
    como put-back (la persona devuelve lo que habia tomado);
  - si la persona se va estando en CON_PRODUCTO, el pick-up se considera
    convertido (takeaway).

Es la misma convencion que usan los estudios de observacion manual en retail, y
es lo que permite calcular la tasa de rechazo (return / pickup) que pide el
reto. Si mas adelante se agrega un clasificador de "mano llena / mano vacia",
solo cambia esta interpretacion, no la estructura.

Robustez: el tracking pierde IDs por oclusion durante 1-2 frames. Un cierre de
episodio inmediato fragmentaria las visitas e inflaria los conteos, asi que la
salida de una zona solo se confirma tras `gracia_frames` frames sin ver a la
persona en ella.

Privacidad (Ley 1581 de 2012): la maquina solo consume numeros (bbox,
timestamps, IDs opacos de ByteTrack). No guarda imagenes, no cruza el
`track_id` con ninguna otra fuente y descarta el estado de un track apenas
termina su episodio.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from reach_detector import BaseReachDetector, Reach, ReachConfig, crear_detector
from zonas import Layout, centroide_bbox


class Estado(str, Enum):
    FUERA = "fuera"
    TRANSITO = "transito"
    DETENIDO = "detenido"
    CON_PRODUCTO = "con_producto"


# Tipos de evento. Los cuatro primeros son los que acepta el validador del
# modulo 8 (Paula). `takeaway` es interno de este modulo: describe la
# conversion (se llevo el producto) y se proyecta fuera del archivo de
# cumplimiento. Ver README, seccion "Doble salida".
EVENTO_APPROACH = "approach"
EVENTO_PICKUP = "pickup"
EVENTO_RETURN = "return"
EVENTO_PASS_BY = "pass_by"
EVENTO_TAKEAWAY = "takeaway"

EVENTOS_COMPLIANCE = {EVENTO_APPROACH, EVENTO_PICKUP, EVENTO_RETURN, EVENTO_PASS_BY}


@dataclass
class Episodio:
    """Una visita continua de un track a una zona."""

    track_id: str
    zone_id: str
    entrada_ms: float
    episodio_id: str = ""
    estado: Estado = Estado.TRANSITO
    ultimo_visto_ms: float = 0.0
    frames_sin_ver: int = 0
    pickups: int = 0
    returns: int = 0
    approach_emitido: bool = False

    def dwell_s(self, ahora_ms: float) -> float:
        return max(0.0, (ahora_ms - self.entrada_ms) / 1000.0)


@dataclass
class Evento:
    """Evento de interaccion en formato canonico (interno del proyecto)."""

    track_id: str
    zone_id: str
    event_type: str
    timestamp_ms: float
    dwell_time_s: float
    confianza: float = 1.0
    episodio_id: str = ""
    detalle: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "track_id": self.track_id,
            "zone_id": self.zone_id,
            "event_type": self.event_type,
            "timestamp_ms": round(self.timestamp_ms, 2),
            "dwell_time_s": round(self.dwell_time_s, 2),
            "confianza": self.confianza,
            "episodio_id": self.episodio_id,
            "detalle": self.detalle,
        }


@dataclass
class InteractionConfig:
    min_dwell_s: float = 2.0        # mismo default que el modulo 5 (Diego)
    gracia_frames: int = 5          # tolerancia a oclusiones del tracker
    solo_gondolas: bool = True      # los pasillos no generan eventos
    min_confianza: float = 0.0      # descarta alcances debiles si se sube


class InteractionStateMachine:
    """
    Procesa `tracking.jsonl` frame a frame y emite eventos de interaccion.

    Uso:
        maquina = InteractionStateMachine(layout)
        for frame in lector:
            maquina.process_frame(frame["timestamp_ms"], frame["tracks"])
        maquina.finalize(ultimo_ts)
        eventos = maquina.eventos
    """

    def __init__(
        self,
        layout: Layout,
        config: InteractionConfig | None = None,
        reach_config: ReachConfig | None = None,
        detector: BaseReachDetector | None = None,
        modo_alcance: str = "geometrico",
        on_event: Callable[[Evento], None] | None = None,
    ):
        self.layout = layout
        self.config = config or InteractionConfig()
        self.detector = detector or crear_detector(modo_alcance, reach_config)
        self.on_event = on_event

        self.episodios: dict[str, Episodio] = {}   # track_id -> episodio activo
        self.eventos: list[Evento] = []
        self.alcances_descartados: list[dict[str, Any]] = []
        self._contador_episodios = 0
        self._frames = 0

    # -- Bucle principal ---------------------------------------------------

    def process_frame(self, timestamp_ms: float, tracks: list[dict[str, Any]]) -> None:
        self._frames += 1
        vistos: set[str] = set()

        for track in tracks:
            if track.get("class", "person") != "person":
                continue
            if "person_id" not in track:
                raise ValueError("Track sin 'person_id' — revisar salida del modulo 3")
            if "bbox" not in track:
                raise ValueError("Track sin 'bbox' — revisar salida del modulo 3")

            track_id = str(track["person_id"])  # contrato: track_id = str(person_id)
            vistos.add(track_id)

            x, y = centroide_bbox(track["bbox"])
            zona = self.layout.zona_de_punto(x, y)

            if zona is None or (self.config.solo_gondolas and not zona.es_gondola):
                self._marcar_ausente(track_id, timestamp_ms)
                continue

            episodio = self.episodios.get(track_id)

            if episodio is not None and episodio.zone_id != zona.zone_id:
                # Cambio de gondola: se cierra el episodio anterior y se abre uno
                # nuevo. Un producto "en la mano" no se arrastra entre zonas.
                self._cerrar_episodio(episodio, timestamp_ms)
                episodio = None

            if episodio is None:
                episodio = self._abrir_episodio(track_id, zona.zone_id, timestamp_ms)

            episodio.frames_sin_ver = 0
            episodio.ultimo_visto_ms = timestamp_ms

            self._actualizar_dwell(episodio, timestamp_ms)

            reach = self.detector.update(track_id, track, timestamp_ms)
            if reach is not None:
                self._procesar_alcance(episodio, reach, timestamp_ms)

        # Tracks con episodio abierto que no aparecieron en este frame
        for track_id in list(self.episodios):
            if track_id not in vistos:
                self._marcar_ausente(track_id, timestamp_ms)

    def finalize(self, timestamp_ms: float) -> None:
        """Cierra los episodios que seguian abiertos al terminar el video."""
        for episodio in list(self.episodios.values()):
            self._cerrar_episodio(episodio, timestamp_ms)
        self.episodios.clear()

    # -- Transiciones ------------------------------------------------------

    def _abrir_episodio(
        self, track_id: str, zone_id: str, timestamp_ms: float
    ) -> Episodio:
        self._contador_episodios += 1
        episodio = Episodio(
            track_id=track_id,
            zone_id=zone_id,
            entrada_ms=timestamp_ms,
            ultimo_visto_ms=timestamp_ms,
            episodio_id=f"{track_id}-{zone_id}-{self._contador_episodios}",
        )
        self.episodios[track_id] = episodio
        return episodio

    def _actualizar_dwell(self, episodio: Episodio, timestamp_ms: float) -> None:
        if episodio.estado is not Estado.TRANSITO:
            return
        if episodio.dwell_s(timestamp_ms) >= self.config.min_dwell_s:
            episodio.estado = Estado.DETENIDO
            self._emitir(
                episodio,
                EVENTO_APPROACH,
                timestamp_ms,
                detalle={"motivo": "dwell supero el umbral"},
            )

    def _procesar_alcance(
        self, episodio: Episodio, reach: Reach, timestamp_ms: float
    ) -> None:
        if not reach.valido:
            self.alcances_descartados.append(
                {
                    "track_id": reach.track_id,
                    "zone_id": episodio.zone_id,
                    "inicio_ms": reach.inicio_ms,
                    "motivo": reach.motivo_descarte,
                }
            )
            return

        if reach.confianza < self.config.min_confianza:
            self.alcances_descartados.append(
                {
                    "track_id": reach.track_id,
                    "zone_id": episodio.zone_id,
                    "inicio_ms": reach.inicio_ms,
                    "motivo": f"confianza {reach.confianza} < minimo",
                }
            )
            return

        detalle = {
            "duracion_alcance_ms": round(reach.duracion_ms, 1),
            "expansion_pico": reach.pico,
            "frames_alcance": reach.frames,
            "detector": self.detector.nombre,
        }

        if episodio.estado is Estado.CON_PRODUCTO:
            episodio.estado = Estado.DETENIDO
            episodio.returns += 1
            self._emitir(
                episodio,
                EVENTO_RETURN,
                timestamp_ms,
                confianza=reach.confianza,
                detalle=detalle,
            )
            return

        # Un alcance implica que la persona se detuvo, aunque el dwell todavia
        # no hubiera cruzado el umbral: se emite el approach para no romper el
        # embudo (no puede haber un pickup sin approach previo).
        if episodio.estado is Estado.TRANSITO:
            episodio.estado = Estado.DETENIDO
            self._emitir(
                episodio,
                EVENTO_APPROACH,
                timestamp_ms,
                detalle={"motivo": "alcance detectado antes del umbral de dwell"},
            )

        episodio.estado = Estado.CON_PRODUCTO
        episodio.pickups += 1
        self._emitir(
            episodio,
            EVENTO_PICKUP,
            timestamp_ms,
            confianza=reach.confianza,
            detalle=detalle,
        )

    def _marcar_ausente(self, track_id: str, timestamp_ms: float) -> None:
        episodio = self.episodios.get(track_id)
        if episodio is None:
            return

        episodio.frames_sin_ver += 1
        if episodio.frames_sin_ver > self.config.gracia_frames:
            self._cerrar_episodio(episodio, episodio.ultimo_visto_ms)

    def _cerrar_episodio(self, episodio: Episodio, timestamp_ms: float) -> None:
        pendiente = self.detector.cerrar(episodio.track_id, timestamp_ms)
        if pendiente is not None and not pendiente.valido:
            self.alcances_descartados.append(
                {
                    "track_id": pendiente.track_id,
                    "zone_id": episodio.zone_id,
                    "inicio_ms": pendiente.inicio_ms,
                    "motivo": pendiente.motivo_descarte,
                }
            )

        if episodio.estado is Estado.TRANSITO:
            self._emitir(
                episodio,
                EVENTO_PASS_BY,
                timestamp_ms,
                detalle={"motivo": "salio sin superar el umbral de dwell"},
            )
        elif episodio.estado is Estado.CON_PRODUCTO:
            self._emitir(
                episodio,
                EVENTO_TAKEAWAY,
                timestamp_ms,
                detalle={
                    "motivo": "salio de la zona tras un pickup sin devolucion",
                    "pickups_episodio": episodio.pickups,
                    "returns_episodio": episodio.returns,
                },
            )

        self.episodios.pop(episodio.track_id, None)
        self.detector.olvidar(episodio.track_id)

    # -- Emision -----------------------------------------------------------

    def _emitir(
        self,
        episodio: Episodio,
        event_type: str,
        timestamp_ms: float,
        confianza: float = 1.0,
        detalle: dict[str, Any] | None = None,
    ) -> None:
        if event_type == EVENTO_APPROACH:
            episodio.approach_emitido = True

        evento = Evento(
            track_id=episodio.track_id,
            zone_id=episodio.zone_id,
            event_type=event_type,
            timestamp_ms=timestamp_ms,
            dwell_time_s=episodio.dwell_s(timestamp_ms),
            confianza=confianza,
            episodio_id=episodio.episodio_id,
            detalle=detalle or {},
        )
        self.eventos.append(evento)
        if self.on_event is not None:
            self.on_event(evento)

    # -- Utilidades --------------------------------------------------------

    @property
    def resumen(self) -> dict[str, Any]:
        conteo: dict[str, int] = {}
        for evento in self.eventos:
            conteo[evento.event_type] = conteo.get(evento.event_type, 0) + 1
        return {
            "frames_procesados": self._frames,
            "episodios": self._contador_episodios,
            "eventos_por_tipo": conteo,
            "alcances_descartados": len(self.alcances_descartados),
            "detector_alcance": self.detector.nombre,
        }
