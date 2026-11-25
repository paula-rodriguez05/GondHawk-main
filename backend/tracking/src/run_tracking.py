"""
run_tracking.py
Pipeline principal del modulo de Tracking de GondHawk.

Entrada:
    JSONL producido por deteccion_personas.

Salida:
    JSONL con las personas trackeadas y su person_id.

Ejemplo:

python tracking/src/run_tracking.py \
    --input deteccion_personas/output/detecciones.jsonl \
    --output tracking/output/tracking.jsonl
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

# Permite ejecutar el script desde la raiz del proyecto.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backend.tracking.src.tracker import PersonTracker


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Tracking de personas con ByteTrack - GondHawk"
    )

    parser.add_argument(
        "--input",
        required=True,
        help="JSONL de detecciones producido por deteccion_personas",
    )

    parser.add_argument(
        "--output",
        required=True,
        help="JSONL donde se guardaran las detecciones trackeadas",
    )

    parser.add_argument(
        "--frame-rate",
        type=float,
        default=None,
        help="FPS del video. Si se omite, se obtiene del archivo .meta.json",
    )

    parser.add_argument(
        "--track-buffer",
        type=int,
        default=30,
        help="Frames que ByteTrack mantiene un track perdido",
    )

    parser.add_argument(
        "--max-frames",
        type=int,
        default=None,
        help="Limite de frames para pruebas",
    )

    return parser.parse_args()


def load_metadata(input_path: Path) -> dict:
    """Obtiene metadata del archivo .meta.json generado por deteccion."""

    meta_path = input_path.with_suffix(".meta.json")

    if not meta_path.exists():
        return {}

    with meta_path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def load_fps(input_path: Path) -> float:
    """Obtiene FPS desde el archivo .meta.json generado por deteccion."""

    meta = load_metadata(input_path)
    return float(meta.get("fps_origen", 30.0))


def load_frame_shape(input_path: Path) -> tuple[int, int, int]:
    """
    Obtiene la resolucion del frame desde el metadata de deteccion.

    Returns:
        Tupla (alto, ancho, canales).
    """

    meta = load_metadata(input_path)

    width = int(meta.get("frame_width", 1280))
    height = int(meta.get("frame_height", 720))

    return (height, width, 3)


def main() -> None:
    args = parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    if not input_path.exists():
        raise FileNotFoundError(
            f"No existe el archivo de entrada: {input_path}"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)

    fps = args.frame_rate if args.frame_rate is not None else load_fps(
        input_path
    )

    frame_shape = load_frame_shape(input_path)
    height, width = frame_shape[:2]

    tracker = PersonTracker(
        track_buffer=args.track_buffer,
        frame_rate=fps,
    )

    frames_processed = 0
    total_tracks = 0
    unique_ids: set[int] = set()

    with (
        input_path.open("r", encoding="utf-8") as input_file,
        output_path.open("w", encoding="utf-8") as output_file,
    ):
        for line in input_file:
            if not line.strip():
                continue

            if (
                args.max_frames is not None
                and frames_processed >= args.max_frames
            ):
                break

            record = json.loads(line)

            frame_id = int(record["frame_id"])
            timestamp_ms = float(record["timestamp_ms"])
            detections = record.get("detections", [])

            tracked = tracker.update(
                detections,
                frame_shape=frame_shape,
            )

            for person in tracked:
                unique_ids.add(person["person_id"])

            total_tracks += len(tracked)

            output_record = {
                "frame_id": frame_id,
                "timestamp_ms": round(timestamp_ms, 2),
                "tracks": tracked,
            }

            output_file.write(
                json.dumps(
                    output_record,
                    ensure_ascii=False,
                )
                + "\n"
            )

            frames_processed += 1

    print(f"[ok] FPS utilizado: {fps}")
    print(f"[ok] Resolucion utilizada: {width}x{height}")
    print(f"[ok] Frames procesados: {frames_processed}")
    print(f"[ok] Tracks generados: {total_tracks}")
    print(f"[ok] Personas únicas identificadas: {len(unique_ids)}")
    print(f"[ok] Salida: {output_path}")


if __name__ == "__main__":
    main()
