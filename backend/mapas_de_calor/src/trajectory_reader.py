"""
trajectory_reader.py — Lee el JSONL que entrega el modulo de tracking (Juan).

v3 — ADAPTADO AL FORMATO REAL de Juan (mergeado a main, PR #3):
    {"frame_id": 0, "timestamp_ms": 0.0, "tracks": [
        {"person_id": 1, "bbox": [x1, y1, x2, y2], "class": "person"}]}

Normalizaciones que hace este lector para que el resto del modulo no se
preocupe por diferencias de formato:
  1. `person_id` (int, como lo emite Juan) se convierte a `track_id` (str).
     Nota: str(int) SIEMPRE pasa el regex del validador del modulo 8
     (Paula): ^[0-9a-fA-F]{1,8}...$ acepta digitos (son caracteres hex).
  2. Si el tracker usara `track_id` en vez de `person_id` (p. ej. la version
     simulada anterior), tambien se acepta.
  3. Si no viene `centroid`, se deriva del `bbox` (punto medio).
"""
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List


@dataclass
class TrackPoint:
    frame_id: int
    timestamp_ms: float
    track_id: str
    centroid: tuple  # (cx, cy)


def _centroid_from_bbox(bbox: List[float]) -> tuple:
    x1, y1, x2, y2 = bbox
    return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)


def _track_id_de(track: dict, line_num: int, path: str) -> str | None:
    """Extrae el ID del track y lo normaliza a string. Acepta person_id (Juan)
    o track_id (formato simulado/alternativo)."""
    pid = track.get("person_id", track.get("track_id"))
    if pid is None:
        print(f"[aviso] linea {line_num} de {path}: track sin person_id/track_id, se ignora")
        return None
    return str(pid)


def read_trajectories(path: str) -> Iterator[TrackPoint]:
    """Itera sobre un archivo JSONL de tracking, un TrackPoint por track por frame."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"No se encontro el archivo de trayectorias: {path}. "
            "Genera el tracking real con tracking/src/run_tracking.py, o usa "
            "simulate_trajectories.py para datos de prueba con el mismo formato."
        )
    with open(p, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as e:
                raise ValueError(f"Linea {line_num} invalida en {path}: {e}") from e

            frame_id = record["frame_id"]
            timestamp_ms = record.get("timestamp_ms", 0.0)
            for track in record.get("tracks", []):
                track_id = _track_id_de(track, line_num, str(p))
                if track_id is None:
                    continue
                centroid = track.get("centroid")
                if centroid is None:
                    bbox = track.get("bbox")
                    if bbox is None:
                        continue  # registro sin posicion util, se ignora
                    centroid = _centroid_from_bbox(bbox)
                yield TrackPoint(
                    frame_id=frame_id,
                    timestamp_ms=timestamp_ms,
                    track_id=track_id,
                    centroid=tuple(centroid),
                )


def load_zonas(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
