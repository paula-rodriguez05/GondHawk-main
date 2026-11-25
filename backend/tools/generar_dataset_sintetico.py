"""
generar_dataset_sintetico.py
Genera un dataset de imágenes etiquetadas a partir del render 3D.
Salida: estructura YOLO lista para entrenar.
"""

import json
import random
import sys
from pathlib import Path

import cv2
import numpy as np

# Añadir la ruta de pipeline/src para importar el generador 3D
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline" / "src"))

from escena3d import GeneradorEscena3D
from humanoide3d import Pose  # <--- Importante


def generar_dataset(
    num_frames_total: int = 5000,
    output_dir: str = "dataset_sintetico",
    seed_base: int = 42,
    train_split: float = 0.8,
):
    out_path = Path(output_dir)
    (out_path / "images" / "train").mkdir(parents=True, exist_ok=True)
    (out_path / "images" / "val").mkdir(parents=True, exist_ok=True)
    (out_path / "labels" / "train").mkdir(parents=True, exist_ok=True)
    (out_path / "labels" / "val").mkdir(parents=True, exist_ok=True)

    frames_por_seed = 200
    seeds = list(range(seed_base, seed_base + (num_frames_total // frames_por_seed) + 2))
    random.shuffle(seeds)

    frame_global = 0
    width, height = 960, 540

    for seed in seeds:
        gen = GeneradorEscena3D(
            ancho=width,
            alto=height,
            fps=15,
            duracion_s=30,
            n_personas=random.randint(8, 18),
            seed=seed,
        )

        personas = gen._crear_personas()
        for p in personas:
            gen._construir_guion(p)

        por_frame = {}
        for p in personas:
            for punto in p.guion:
                por_frame.setdefault(punto["frame"], []).append((p, punto))

        estaticas = gen.tienda.estaticas

        for frame_id in range(gen.total_frames):
            if frame_global >= num_frames_total:
                break

            mallas = list(estaticas)
            anotaciones = []

            for persona, punto in por_frame.get(frame_id, []):
                pose = Pose(
                    fase_paso=punto["fase"],
                    alcance=punto["alcance"],
                    alcance_derecho=True,
                    giro_cuerpo=punto["giro"],
                )
                posicion = np.array([punto["x"], 0.0, punto["z"]])
                mallas.extend(persona.humanoide.mallas(posicion, pose))

                bbox = gen.renderer.bbox_de(
                    persona.humanoide.malla_unida(posicion, pose)
                )
                if bbox and bbox[2] - bbox[0] > 4 and bbox[3] - bbox[1] > 8:
                    anotaciones.append({
                        "bbox": list(bbox),
                        "class": "person",
                    })

            if not anotaciones:
                continue

            img = gen.renderer.render(mallas)
            img = np.clip(img.astype(np.int16) + np.random.normal(0, 3.0, img.shape), 0, 255).astype(np.uint8)

            split = "train" if frame_global % 10 < int(train_split * 10) else "val"

            img_path = out_path / "images" / split / f"frame_{frame_global:06d}.jpg"
            label_path = out_path / "labels" / split / f"frame_{frame_global:06d}.txt"

            cv2.imwrite(str(img_path), img)

            h, w = img.shape[:2]
            with open(label_path, "w", encoding="utf-8") as f:
                for ann in anotaciones:
                    x1, y1, x2, y2 = ann["bbox"]
                    x1 = max(0, x1)
                    y1 = max(0, y1)
                    x2 = min(w - 1, x2)
                    y2 = min(h - 1, y2)
                    if x2 <= x1 or y2 <= y1:
                        continue
                    x_center = (x1 + x2) / 2.0 / w
                    y_center = (y1 + y2) / 2.0 / h
                    width_norm = (x2 - x1) / w
                    height_norm = (y2 - y1) / h
                    f.write(f"0 {x_center:.6f} {y_center:.6f} {width_norm:.6f} {height_norm:.6f}\n")

            frame_global += 1
            if frame_global % 100 == 0:
                print(f"Generados {frame_global} frames...")

            if frame_global >= num_frames_total:
                break

    yaml_content = f"""
path: {out_path.resolve()}
train: images/train
val: images/val

nc: 1
names: ['person']
"""
    (out_path / "data.yaml").write_text(yaml_content.strip(), encoding="utf-8")
    print(f"\n✅ Dataset generado en {out_path}")
    print(f"   Total frames: {frame_global}")
    print(f"   data.yaml creado.")


if __name__ == "__main__":
    generar_dataset(num_frames_total=500)