"""
trajectory_reader.py
Lector centralizado para tracking.jsonl - evita duplicación de código.

Proporciona funciones para leer y procesar las trayectorias de personas
generadas por el módulo de tracking (integrante 3).

Contrato de datos esperado en tracking.jsonl (sección 4 de FORMATO_DATOS.md):
    - centroide = punto medio del bbox
    - track_id como str(person_id)
    - timestamp_ms en milisegundos

Ejemplo de uso:
    reader = TrajectoryReader(Path("tracking/output/tracking.jsonl"))
    for frame_data in reader.read():
        for track in frame_data["tracks"]:
            centroide = reader.get_centroid(track["bbox"])
            track_id = reader.get_track_id(track["person_id"])
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Generator

import numpy as np


class TrajectoryReader:
    """Lector de trayectorias desde tracking.jsonl."""

    def __init__(self, input_path: Path):
        """
        Inicializa el lector.

        Args:
            input_path: Ruta a tracking.jsonl

        Raises:
            FileNotFoundError: si el archivo de tracking no existe.
        """
        self.input_path = Path(input_path)
        if not self.input_path.exists():
            raise FileNotFoundError(
                f"No existe el archivo de tracking: {self.input_path}"
            )

    @staticmethod
    def get_centroid(bbox: list[float]) -> np.ndarray:
        """
        Calcula el centroide (punto medio) de un bounding box.

        Contrato: centroide = ((x1+x2)/2, (y1+y2)/2)

        Args:
            bbox: [x1, y1, x2, y2] en píxeles

        Returns:
            ndarray con [x_centro, y_centro]

        Raises:
            ValueError: si el bbox no tiene 4 coordenadas numéricas válidas.
        """
        if bbox is None or not isinstance(bbox, (list, tuple)):
            raise ValueError("bbox debe ser una lista [x1, y1, x2, y2]")

        if len(bbox) != 4:
            raise ValueError(
                f"bbox debe tener exactamente 4 coordenadas, se obtuvieron {len(bbox)}: {bbox}"
            )

        try:
            x1, y1, x2, y2 = (float(v) for v in bbox)
        except (TypeError, ValueError):
            raise ValueError(
                f"bbox contiene coordenadas no numéricas: {bbox}"
            ) from None

        if x2 < x1 or y2 < y1:
            raise ValueError(
                f"bbox inválido: (x2,y2) debe ser >= (x1,y1): {bbox}"
            )

        return np.array([(x1 + x2) / 2.0, (y1 + y2) / 2.0])

    @staticmethod
    def get_track_id(person_id: Any) -> str:
        """
        Convierte un person_id a track_id según el contrato.

        Contrato: track_id = str(person_id)

        Args:
            person_id: ID de la persona como int o valor numérico.

        Returns:
            track_id como string exactamente str(person_id).

        Raises:
            ValueError: si person_id es None o no es convertible a un entero.
        """
        if person_id is None:
            raise ValueError("person_id es obligatorio en el track")

        if isinstance(person_id, bool):
            raise ValueError(f"person_id no puede ser booleano: {person_id}")

        try:
            return str(int(person_id))
        except (TypeError, ValueError):
            raise ValueError(
                f"person_id debe ser un entero, se obtuvo: {person_id!r}"
            ) from None

    @staticmethod
    def _validate_frame(record: dict[str, Any]) -> None:
        """Valida la estructura básica de un registro de frame (opcional)."""
        if not isinstance(record, dict):
            raise ValueError(f"Registro de frame inválido (no es dict): {record!r}")

        if not isinstance(record.get("tracks", []), list):
            raise ValueError(
                f"'tracks' debe ser una lista en el frame: {record.get('frame_id')!r}"
            )

    @staticmethod
    def _validate_track(track: dict[str, Any]) -> None:
        """Valida la estructura básica de un track (opcional)."""
        if not isinstance(track, dict):
            raise ValueError(f"Track inválido (no es dict): {track!r}")

        track_class = track.get("class")
        if track_class is not None and not isinstance(track_class, str):
            raise ValueError(f"Campo 'class' inválido en track: {track_class!r}")

    def read(self) -> Generator[dict[str, Any], None, None]:
        """
        Lee tracking.jsonl línea por línea.

        Yields:
            dict con frame_id, timestamp_ms y tracks

        Raises:
            ValueError: si una línea no es JSON válido.
        """
        with self.input_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue

                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"Línea inválida en tracking.jsonl: {line!r}"
                    ) from exc

                self._validate_frame(record)
                yield record

    def read_all(self) -> list[dict[str, Any]]:
        """
        Lee todo el archivo de tracking en memoria.

        NOTA: Usar solo en pruebas o datos pequeños. Para producción
        usar read() que procesa en streaming.

        Returns:
            Lista de registros del archivo
        """
        return list(self.read())
