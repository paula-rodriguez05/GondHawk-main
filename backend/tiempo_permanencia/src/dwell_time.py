"""
dwell_time.py
Módulo de Tiempo de Permanencia en Góndolas — GondHawk Integrante 5.

Lee el JSONL generado por tracking (integrante 3) y calcula cuánto
tiempo cada persona permaneció en las zonas definidas por el integrante 4.

Entrada:
    - tracking/output/tracking.jsonl (generado por integrante 3)
    - zonas.json (fuente única de zonas, proporcionado por integrante 4)

Salida:
    - tiempo_permanencia/output/dwell_time.jsonl
      Formato: {track_id, zone_id, dwell_time_s, timestamp_ms, detuvo}

Referencia temporal:
    - timestamp_ms es la única fuente de verdad temporal para el dwell.
    - frame_id pertenece al contrato de tracking pero NO participa en el
      cálculo de permanencia (se conserva en tracking.jsonl, no se usa aquí).

Centroide (contrato):
    - centroide = punto medio del bbox: ((x1+x2)/2, (y1+y2)/2)

track_id (contrato):
    - track_id = str(person_id)

Ejemplo de uso:

python tiempo_permanencia/src/dwell_time.py \\
    --input tracking/output/tracking.jsonl \\
    --zonas mapas_de_calor/config/zonas.json \\
    --output tiempo_permanencia/output/dwell_time.jsonl \\
    --min-dwell 2.0 \\
    --gracia-frames 2
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from trajectory_reader import TrajectoryReader

DEFAULT_ZONES_PATH = (
    Path(__file__).resolve().parents[2] / "mapas_de_calor" / "config" / "zonas.json"
)


class ZoneConfigError(ValueError):
    """Error de configuración de zonas (geometría inválida)."""


class DwellTimeAnalyzer:
    """
    Analiza tiempo de permanencia por zona usando trayectorias de tracking.

    Modelo de estado:
        - clave: (track_id, zone_id)
        - valor: timestamp_ms de entrada a la zona.
    - Un evento de dwell se genera cuando la persona sale de la zona.
    - detuvo = True si dwell_time_s >= umbral configurado.

    NOTA: Se emiten TODOS los eventos válidos, incluyendo aquellos con
    detuvo=False (personas que pasaron rápido). El umbral solo decide el
    valor del flag detuvo, no descarta registros.
    """

    def __init__(
        self,
        zones: dict[str, dict[str, Any]],
        min_dwell_ms: float = 2000.0,
        grace_frames: int = 2,
    ):
        """
        Inicializa el analizador.

        Args:
            zones: dict con estructura de zonas {zone_id: {vertices, ...}}
            min_dwell_ms: tiempo mínimo en ms para considerar que se detuvo
            grace_frames: número de frames consecutivos sin ver el track antes
                de cerrar formalmente el evento para esa zona.

        Raises:
            ZoneConfigError: si una zona tiene geometría inválida.
        """
        if min_dwell_ms < 0:
            raise ValueError("min_dwell_ms no puede ser negativo")
        if grace_frames < 0:
            raise ValueError("grace_frames no puede ser negativo")

        self.zones = zones
        self.min_dwell_ms = min_dwell_ms
        self.grace_frames = int(grace_frames)

        # Convertir vértices a arrays de numpy para cv2.pointPolygonTest
        self.zone_polygons: dict[str, np.ndarray] = {}
        for zone_id, zone_data in zones.items():
            self.zone_polygons[zone_id] = self._validar_vertices(
                zone_id, zone_data
            )

        # Estado: {(track_id, zone_id): entry_timestamp_ms}
        self.active: dict[tuple[str, str], float] = {}
        self.absent_frames: dict[tuple[str, str], int] = {}

        # Eventos de dwell generados
        self.events: list[dict[str, Any]] = []

    @staticmethod
    def _validar_vertices(
        zone_id: str,
        zone_data: dict[str, Any],
    ) -> np.ndarray:
        """
        Valida y convierte los vértices de una zona a un polígono numpy.

        Raises:
            ZoneConfigError: si la zona no tiene vértices o su geometría
                es inválida.
        """
        zone_name = zone_data.get("name", zone_id)
        vertices = zone_data.get("vertices")

        if not vertices:
            raise ZoneConfigError(
                f"Zona '{zone_id}' ({zone_name}) no tiene vértices definidos"
            )

        if not isinstance(vertices, (list, tuple)):
            raise ZoneConfigError(
                f"Zona '{zone_id}' ({zone_name}): 'vertices' debe ser una lista de puntos"
            )

        if len(vertices) < 3:
            raise ZoneConfigError(
                f"Zona '{zone_id}' ({zone_name}) necesita al menos 3 vértices "
                f"(polígono), se definieron {len(vertices)}"
            )

        try:
            polygon = np.array(vertices, dtype=np.float32)
        except (TypeError, ValueError):
            raise ZoneConfigError(
                f"Zona '{zone_id}' ({zone_name}) tiene vértices con formato inválido"
            ) from None

        if polygon.shape[1] != 2:
            raise ZoneConfigError(
                f"Zona '{zone_id}' ({zone_name}): cada vértice debe ser [x, y]"
            )

        return polygon

    def _get_zone_for_point(self, point: np.ndarray) -> str | None:
        """
        Determina en qué zona está un punto usando cv2.pointPolygonTest.

        Args:
            point: array [x, y]

        Returns:
            zone_id o None si está fuera de todas las zonas
        """
        pt = (float(point[0]), float(point[1]))
        for zone_id, polygon in self.zone_polygons.items():
            result = cv2.pointPolygonTest(polygon, pt, False)
            if result >= 0:  # dentro o en el borde
                return zone_id
        return None

    def process_frame(
        self,
        timestamp_ms: float,
        tracks: list[dict[str, Any]],
    ) -> None:
        """
        Procesa un frame de tracking.

        El cálculo temporal usa únicamente timestamp_ms. frame_id NO se
        utiliza en el cálculo de permanencia.

        Args:
            timestamp_ms: timestamp del frame en milisegundos.
            tracks: lista de tracks con person_id, bbox, class.
        """
        seen: set[tuple[str, str]] = set()
        seen_track_ids: set[str] = set()
        track_zones: dict[str, set[str]] = {}

        for track in tracks:
            if track.get("class") != "person":
                continue

            if "person_id" not in track:
                raise ValueError("Track sin person_id")

            track_id = TrajectoryReader.get_track_id(track["person_id"])

            if "bbox" not in track:
                raise ValueError(f"Track {track_id} sin bbox")

            bbox = track["bbox"]
            centroid = TrajectoryReader.get_centroid(bbox)
            zone_id = self._get_zone_for_point(centroid)

            if zone_id is None:
                continue

            seen_track_ids.add(track_id)
            track_zones.setdefault(track_id, set()).add(zone_id)
            key = (track_id, zone_id)
            seen.add(key)

            if key not in self.active:
                self.active[key] = timestamp_ms
            self.absent_frames.pop(key, None)

        for key in list(self.active):
            track_id, zone_id = key
            if key in seen:
                continue

            is_transition = (
                track_id in seen_track_ids
                and zone_id not in track_zones.get(track_id, set())
            )

            if is_transition:
                entry_ms = self.active.pop(key)
                self.absent_frames.pop(key, None)
                dwell_ms = timestamp_ms - entry_ms
                self._emit_event(track_id, zone_id, entry_ms, dwell_ms)
                continue

            missing_frames = self.absent_frames.get(key, 0) + 1
            self.absent_frames[key] = missing_frames

            if missing_frames >= self.grace_frames:
                entry_ms = self.active.pop(key)
                self.absent_frames.pop(key, None)
                dwell_ms = timestamp_ms - entry_ms
                self._emit_event(track_id, zone_id, entry_ms, dwell_ms)

    def _emit_event(
        self,
        track_id: str,
        zone_id: str,
        entry_ms: float,
        dwell_ms: float,
    ) -> None:
        """Genera un evento de dwell. detuvo = dwell_ms >= min_dwell_ms."""
        dwell_s = dwell_ms / 1000.0
        self.events.append(
            {
                "track_id": track_id,
                "zone_id": zone_id,
                "dwell_time_s": round(dwell_s, 2),
                "timestamp_ms": round(entry_ms, 2),
                "detuvo": dwell_ms >= self.min_dwell_ms,
            }
        )

    def finalize(self, final_timestamp_ms: float) -> None:
        """
        Finaliza el análisis: genera eventos para las personas
        que aún estaban en una zona al final del video.

        Args:
            final_timestamp_ms: timestamp del último frame.
        """
        for key, entry_ms in list(self.active.items()):
            track_id, zone_id = key
            dwell_ms = final_timestamp_ms - entry_ms
            self._emit_event(track_id, zone_id, entry_ms, dwell_ms)

        self.active.clear()
        self.absent_frames.clear()

    def get_events(self) -> list[dict[str, Any]]:
        """Retorna la lista de eventos de dwell."""
        return self.events


def load_zones_from_json(zones_path: Path | str | None = None) -> dict[str, dict[str, Any]]:
    """
    Carga las zonas desde el catálogo oficial del proyecto.

    Args:
        zones_path: ruta a zonas.json. Si es None, usa el catálogo unificado en
            mapas_de_calor/config/zonas.json.

    Returns:
        dict con la estructura de zonas

    Raises:
        FileNotFoundError: si el archivo no existe.
        ValueError: si el archivo no tiene el campo 'zones' o está vacío.
    """
    if zones_path is None:
        zones_path = DEFAULT_ZONES_PATH
    zones_path = Path(zones_path)

    if not zones_path.exists():
        raise FileNotFoundError(f"No existe el archivo de zonas: {zones_path}")

    with zones_path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)

    if not isinstance(data, dict) or "zonas" not in data:
        raise ValueError(
            f"zonas.json debe tener un campo 'zonas': {zones_path}"
        )

    zonas = data.get("zonas", [])
    if not zonas:
        raise ValueError(f"No se encontraron zonas en {zones_path}")

    zones = {z["zone_id"]: {"vertices": z["poligono"]} for z in zonas}

    return zones


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Análisis de Tiempo de Permanencia en Góndolas — GondHawk"
    )

    parser.add_argument(
        "--input",
        required=True,
        help="JSONL generado por tracking (tracking.jsonl)",
    )

    parser.add_argument(
        "--zonas",
        default=str(DEFAULT_ZONES_PATH),
        help="Archivo de configuración de zonas (default: mapas_de_calor/config/zonas.json)",
    )

    parser.add_argument(
        "--output",
        required=True,
        help="JSONL de salida con eventos de dwell_time",
    )

    parser.add_argument(
        "--min-dwell",
        type=float,
        default=2.0,
        help="Tiempo mínimo de permanencia en segundos (default: 2.0)",
    )

    parser.add_argument(
        "--gracia-frames",
        type=int,
        default=2,
        help="Frames consecutivos sin ver el track antes de cerrar el dwell (default: 2)",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # Validación de archivos de entrada realizada por los objetos mismos
    # (TrajectoryReader y load_zones_from_json lanzan FileNotFoundError).
    zones = load_zones_from_json(Path(args.zonas))

    min_dwell_ms = args.min_dwell * 1000.0
    analyzer = DwellTimeAnalyzer(
        zones,
        min_dwell_ms=min_dwell_ms,
        grace_frames=args.gracia_frames,
    )

    reader = TrajectoryReader(Path(args.input))
    final_timestamp_ms = 0.0

    for frame_data in reader.read():
        timestamp_ms = float(frame_data.get("timestamp_ms", 0.0))
        tracks = frame_data.get("tracks", [])

        analyzer.process_frame(timestamp_ms, tracks)
        final_timestamp_ms = timestamp_ms

    # Finalizar: generar eventos para tracks que aún estaban activos
    analyzer.finalize(final_timestamp_ms)

    events = analyzer.get_events()

    # Escribir salida
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8") as fh:
        for event in events:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")

    # Estadísticas
    zone_stats: dict[str, dict[str, Any]] = {}
    for event in events:
        zone_id = event["zone_id"]
        if zone_id not in zone_stats:
            zone_stats[zone_id] = {
                "count": 0,
                "total_dwell_s": 0.0,
                "detuvo_count": 0,
            }
        zone_stats[zone_id]["count"] += 1
        zone_stats[zone_id]["total_dwell_s"] += event["dwell_time_s"]
        if event["detuvo"]:
            zone_stats[zone_id]["detuvo_count"] += 1

    print(f"[ok] Archivo de entrada: {reader.input_path}")
    print(f"[ok] Archivo de zonas: {Path(args.zonas)}")
    print(f"[ok] Zonas definidas: {len(zones)}")
    print(f"[ok] Tiempo mínimo de permanencia: {args.min_dwell:.1f}s")
    print(f"[ok] Eventos de dwell: {len(events)}")

    if events:
        total_dwell = sum(e["dwell_time_s"] for e in events)
        avg_dwell = total_dwell / len(events)
        detuvo_count = sum(1 for e in events if e["detuvo"])
        print(f"[ok] Tiempo promedio de permanencia: {avg_dwell:.1f}s")
        print(f"[ok] Eventos con 'detuvo=True': {detuvo_count}")
        print(f"[ok] Eventos con 'detuvo=False': {len(events) - detuvo_count}")

    print("\n[ok] Por zona:")
    for zone_id, stats in sorted(zone_stats.items()):
        avg_zone = stats["total_dwell_s"] / stats["count"]
        print(
            f"[ok]   {zone_id}: {stats['count']} eventos, "
            f"promedio {avg_zone:.1f}s, "
            f"detuvo: {stats['detuvo_count']}"
        )

    print(f"\n[ok] Salida: {output_path}")


if __name__ == "__main__":
    main()
