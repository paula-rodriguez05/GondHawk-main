import argparse
import json
from pathlib import Path

import cv2


def parse_args():
    parser = argparse.ArgumentParser(
        description="Genera un video visualizando los IDs de tracking."
    )

    parser.add_argument("--video", required=True)
    parser.add_argument("--tracking", required=True)
    parser.add_argument("--output", required=True)

    return parser.parse_args()


def load_tracking(path):
    tracking = {}

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue

            record = json.loads(line)
            tracking[int(record["frame_id"])] = record["tracks"]

    return tracking


def main():
    args = parse_args()

    video_path = Path(args.video)
    tracking_path = Path(args.tracking)
    output_path = Path(args.output)

    if not video_path.exists():
        raise FileNotFoundError(f"No existe el video: {video_path}")

    if not tracking_path.exists():
        raise FileNotFoundError(
            f"No existe el archivo de tracking: {tracking_path}"
        )

    tracking_data = load_tracking(tracking_path)

    cap = cv2.VideoCapture(str(video_path))

    if not cap.isOpened():
        raise RuntimeError(f"No se pudo abrir el video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 10.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    output_path.parent.mkdir(parents=True, exist_ok=True)

    fourcc = cv2.VideoWriter_fourcc(*"XVID")
    writer = cv2.VideoWriter(
        str(output_path),
        fourcc,
        fps,
        (width, height),
    )

    frame_id = 0

    while True:
        ok, frame = cap.read()

        if not ok:
            break

        tracks = tracking_data.get(frame_id, [])

        for person in tracks:
            person_id = person["person_id"]
            x1, y1, x2, y2 = map(int, person["bbox"])

            cv2.rectangle(
                frame,
                (x1, y1),
                (x2, y2),
                (0, 255, 0),
                2,
            )

            label = f"ID: {person_id}"

            cv2.rectangle(
                frame,
                (x1, max(0, y1 - 25)),
                (x1 + 80, y1),
                (0, 255, 0),
                -1,
            )

            cv2.putText(
                frame,
                label,
                (x1 + 4, max(18, y1 - 7)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (0, 0, 0),
                2,
            )

        cv2.putText(
            frame,
            f"Frame: {frame_id} | Personas: {len(tracks)}",
            (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.75,
            (255, 255, 255),
            2,
        )

        writer.write(frame)

        frame_id += 1

    cap.release()
    writer.release()

    print("[ok] Video generado")
    print(f"[ok] Frames: {frame_id}")
    print(f"[ok] FPS: {fps}")
    print(f"[ok] Resolucion: {width}x{height}")
    print(f"[ok] Salida: {output_path}")


if __name__ == "__main__":
    main()
