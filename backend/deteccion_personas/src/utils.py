"""Utilidades de video/IO para el modulo de deteccion de personas."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator, Tuple

import cv2
import numpy as np


class VideoReader:
    """Iterador simple sobre los frames de un video (o webcam)."""

    def __init__(self, source: str | int):
        # source puede ser una ruta a archivo, o un entero (0 = webcam por defecto)
        self.source = source
        self.cap = cv2.VideoCapture(source)
        if not self.cap.isOpened():
            raise RuntimeError(f"No se pudo abrir la fuente de video: {source}")

        self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 0.0
        self.width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.frame_count = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))

    def __iter__(self) -> Iterator[Tuple[int, float, np.ndarray]]:
        frame_id = 0
        while True:
            ok, frame = self.cap.read()
            if not ok:
                break
            timestamp_ms = (frame_id / self.fps * 1000.0) if self.fps else 0.0
            yield frame_id, timestamp_ms, frame
            frame_id += 1

    def release(self):
        self.cap.release()


class JsonlWriter:
    """Escribe una linea JSON por frame (formato JSONL), facil de leer
    en streaming por el modulo de Tracking (integrante 3)."""

    def __init__(self, output_path: str | Path):
        self.output_path = Path(output_path)
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.output_path, "w", encoding="utf-8")

    def write_frame(self, frame_id: int, timestamp_ms: float, detections: list[dict]):
        record = {
            "frame_id": frame_id,
            "timestamp_ms": round(timestamp_ms, 2),
            "detections": detections,
        }
        self._fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    def close(self):
        self._fh.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


def draw_detections(frame: np.ndarray, detections: list[dict]) -> np.ndarray:
    """Dibuja los bounding boxes de personas sobre una COPIA del frame.

    Solo para verificacion visual del propio equipo durante el desarrollo.
    No se guardan recortes de caras ni ningun dato biometrico: solamente
    se pinta un rectangulo sobre la posicion de la persona detectada.
    """
    out = frame.copy()
    for det in detections:
        x1, y1, x2, y2 = [int(v) for v in det["bbox"]]
        conf = det["confidence"]
        cv2.rectangle(out, (x1, y1), (x2, y2), (0, 200, 0), 2)
        label = f"person {conf:.2f}"
        cv2.putText(
            out, label, (x1, max(y1 - 8, 0)),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 200, 0), 2,
        )
    return out
