"""
run_detection.py
Script principal del modulo de Deteccion de Personas.

Ejemplos de uso:

  # Procesar un video y guardar las detecciones en JSONL
  python src/run_detection.py --source data/vtest.avi --output output/detecciones.jsonl

  # Ademas guardar un video anotado para verificar visualmente
  python src/run_detection.py --source data/vtest.avi --output output/detecciones.jsonl --save-video output/preview.mp4

  # Probar con la webcam (fuente 0), solo 200 frames
  python src/run_detection.py --source 0 --output output/detecciones.jsonl --max-frames 200
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import cv2

from backend.deteccion_personas.src.person_detector import PersonDetector
from backend.deteccion_personas.src.utils import VideoReader, JsonlWriter, draw_detections


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Deteccion de personas con YOLO (GondHawk)")
    parser.add_argument("--source", required=True, help="Ruta al video, o '0' para webcam")
    parser.add_argument("--output", required=True, help="Ruta del archivo JSONL de salida")
    parser.add_argument("--model", default="yolov8n.pt", help="Pesos de YOLO a usar")
    parser.add_argument("--conf", type=float, default=0.4, help="Umbral de confianza")
    parser.add_argument("--save-video", default=None, help="Ruta opcional para guardar video anotado (solo verificacion, no se sube al repo)")
    parser.add_argument("--max-frames", type=int, default=None, help="Limite de frames a procesar (util para pruebas rapidas)")
    parser.add_argument("--device", default=None, help="'cpu', 'cuda', etc. (por defecto: automatico)")
    return parser.parse_args()


def main():
    args = parse_args()

    source = int(args.source) if args.source.isdigit() else args.source

    detector = PersonDetector(model_path=args.model, conf_threshold=args.conf, device=args.device)
    reader = VideoReader(source)

    print(f"[info] fuente={source} fps={reader.fps:.2f} size={reader.width}x{reader.height} frames={reader.frame_count}")

    video_writer = None
    if args.save_video:
        Path(args.save_video).parent.mkdir(parents=True, exist_ok=True)
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        fps_out = reader.fps if reader.fps > 0 else 25.0
        video_writer = cv2.VideoWriter(args.save_video, fourcc, fps_out, (reader.width, reader.height))

    total_detections = 0
    n_frames = 0
    t0 = time.time()

    with JsonlWriter(args.output) as writer:
        for frame_id, timestamp_ms, frame in reader:
            if args.max_frames is not None and frame_id >= args.max_frames:
                break

            detections = detector.detect_frame(frame)
            det_dicts = [d.to_dict() for d in detections]
            writer.write_frame(frame_id, timestamp_ms, det_dicts)

            total_detections += len(det_dicts)
            n_frames += 1

            if video_writer is not None:
                annotated = draw_detections(frame, det_dicts)
                video_writer.write(annotated)

    reader.release()
    if video_writer is not None:
        video_writer.release()

    elapsed = time.time() - t0
    meta = {
        "video_source": str(source),
        "fps_origen": reader.fps,
        "frame_width": reader.width,
        "frame_height": reader.height,
        "frames_procesados": n_frames,
        "total_detecciones": total_detections,
        "tiempo_procesamiento_seg": round(elapsed, 2),
        "modelo": args.model,
        "conf_threshold": args.conf,
    }
    meta_path = Path(args.output).with_suffix(".meta.json")
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"[ok] {n_frames} frames procesados, {total_detections} detecciones totales en {elapsed:.1f}s")
    print(f"[ok] JSONL: {args.output}")
    print(f"[ok] metadata: {meta_path}")
    if video_writer is not None:
        print(f"[ok] video anotado: {args.save_video}")


if __name__ == "__main__":
    main()
