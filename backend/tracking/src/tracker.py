"""
tracker.py
Modulo de Tracking de personas - GondHawk.

Recibe detecciones de personas y asigna un person_id persistente
utilizando ByteTrack de Ultralytics.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import torch

from ultralytics.engine.results import Boxes
from ultralytics.trackers.byte_tracker import BYTETracker


class ByteTrackInput:
    """
    Adaptador compatible con la API de BYTETracker de Ultralytics 8.4.x.

    BYTETracker espera directamente:
        results.conf
        results.xywh
        results.xyxy
        results.cls

    No espera un objeto Results completo.
    """

    def __init__(
        self,
        boxes: torch.Tensor,
        orig_shape: tuple[int, int],
    ):
        self.boxes = Boxes(boxes, orig_shape=orig_shape)

    @property
    def conf(self):
        return self.boxes.conf

    @property
    def xywh(self):
        return self.boxes.xywh

    @property
    def xyxy(self):
        return self.boxes.xyxy

    @property
    def cls(self):
        return self.boxes.cls

    def __len__(self):
        return len(self.boxes)

    def __getitem__(self, index):
        selected = self.boxes[index]

        # Crear un nuevo adaptador con las cajas seleccionadas.
        data = selected.data
        return ByteTrackInput(
            data,
            self.boxes.orig_shape,
        )


class PersonTracker:
    """Asigna IDs persistentes a personas usando ByteTrack."""

    def __init__(
        self,
        track_high_thresh: float = 0.5,
        track_low_thresh: float = 0.1,
        new_track_thresh: float = 0.6,
        track_buffer: int = 30,
        match_thresh: float = 0.8,
        frame_rate: float = 30.0,
    ):
        self.args = type(
            "TrackerArgs",
            (),
            {
                "track_high_thresh": track_high_thresh,
                "track_low_thresh": track_low_thresh,
                "new_track_thresh": new_track_thresh,
                "track_buffer": track_buffer,
                "match_thresh": match_thresh,
                "fuse_score": True,
                "with_reid": False,
                "proximity_thresh": 0.5,
                "appearance_thresh": 0.25,
                "gmc_method": "sparseOptFlow",
            },
        )()

        # Ultralytics 8.4.x recibe solamente args.
        self.tracker = BYTETracker(self.args)

        self.frame_rate = frame_rate
        self.frame_shape = (720, 1280, 3)

    def update(
        self,
        detections: list[dict[str, Any]],
        frame_shape: tuple[int, int, int] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Procesa las detecciones de un frame.

        Args:
            detections:
                Lista de detecciones provenientes del modulo YOLO.

            frame_shape:
                (alto, ancho, canales) del frame.

        Returns:
            Lista de personas con person_id y bounding box.
        """

        if frame_shape is not None:
            self.frame_shape = frame_shape

        height, width = self.frame_shape[:2]

        rows = []

        for det in detections:
            x1, y1, x2, y2 = det["bbox"]
            confidence = float(det["confidence"])

            rows.append(
                [
                    float(x1),
                    float(y1),
                    float(x2),
                    float(y2),
                    confidence,
                    0.0,
                ]
            )

        if rows:
            tensor = torch.tensor(
                rows,
                dtype=torch.float32,
            )
        else:
            tensor = torch.empty(
                (0, 6),
                dtype=torch.float32,
            )

        results = ByteTrackInput(
            tensor,
            orig_shape=(height, width),
        )

        tracks = self.tracker.update(results, None)

        output = []

        for track in tracks:
            x1, y1, x2, y2, track_id = track[:5]

            output.append(
                {
                    "person_id": int(track_id),
                    "bbox": [
                        round(float(x1), 1),
                        round(float(y1), 1),
                        round(float(x2), 1),
                        round(float(y2), 1),
                    ],
                    "class": "person",
                }
            )

        return output
