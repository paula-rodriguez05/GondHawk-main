"""
simular_tracking.py
Generador de tracking.jsonl sintetico — Modulo 1, GondHawk.

Sirve para dos cosas:

1. Desbloquear el desarrollo: la maquina de estados se puede programar y
   probar sin esperar a que el modulo 3 termine de correr sobre el video.
2. Validar exactitud: como el simulador SABE que hizo cada persona, escribe
   junto al JSONL un archivo `ground_truth.json` con los eventos esperados.
   Comparar eventos detectados vs. esperados da la metrica de exactitud que
   pide el reto ("exactitud en la deteccion de eventos").

Comportamientos simulados:
    pass_by       entra a la gondola y sigue de largo (< umbral de dwell)
    approach      se detiene frente a la gondola pero no toca nada
    pickup        se detiene, estira el brazo y se va con el producto
    pickup_return se detiene, toma el producto y lo devuelve al estante
    pasillo       circula por el pasillo, nunca entra a una gondola

El alcance se simula ensanchando el bbox (el brazo extendido ensancha la
silueta) sin cambiar la altura, que es exactamente la senal que consume el
detector geometrico.

Uso:
    python deteccion_eventos/tools/simular_tracking.py \\
        --zonas mapas_de_calor/config/zonas.json \\
        --output deteccion_eventos/output/tracking_sintetico.jsonl \\
        --personas 24 --seed 7
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from zonas import cargar_layout  # noqa: E402

ESCENARIOS = ["pass_by", "approach", "pickup", "pickup_return", "pasillo"]
PESOS = [0.22, 0.20, 0.26, 0.22, 0.10]

ALTO_PERSONA = 92.0
ANCHO_PERSONA = 40.0
FACTOR_ALCANCE = 1.42   # el brazo extendido ensancha ~40% la silueta
RUIDO_PX = 0.6          # jitter del detector, en pixeles


def _plan_persona(
    person_id: int,
    escenario: str,
    zona,
    pasillo,
    frame_inicio: int,
    fps: float,
    rng: random.Random,
    factor_alcance: float = FACTOR_ALCANCE,
    ruido_px: float = RUIDO_PX,
) -> dict[str, Any]:
    """Construye el guion de una persona: por cada frame, su bbox."""
    dt = 1.0 / fps
    cx, cy = zona.centroide if zona is not None else pasillo.centroide

    frames: list[tuple[int, list[float]]] = []
    eventos_esperados: list[dict[str, Any]] = []
    f = frame_inicio

    def poner(x: float, y: float, ancho: float = ANCHO_PERSONA) -> None:
        nonlocal f
        jx = rng.uniform(-ruido_px, ruido_px)
        jy = rng.uniform(-ruido_px, ruido_px)
        frames.append(
            (
                f,
                [
                    round(x - ancho / 2 + jx, 1),
                    round(y - ALTO_PERSONA / 2 + jy, 1),
                    round(x + ancho / 2 + jx, 1),
                    round(y + ALTO_PERSONA / 2 + jy, 1),
                ],
            )
        )
        f += 1

    # Aproximacion desde el pasillo (fuera de la zona objetivo)
    y_pasillo = pasillo.centroide[1]
    for i in range(6):
        poner(cx - 120 + i * 20, y_pasillo)

    if escenario == "pasillo":
        for i in range(20):
            poner(cx + i * 12, y_pasillo)
        return {"person_id": person_id, "frames": frames, "esperados": eventos_esperados}

    # Entra a la zona de gondola
    if escenario == "pass_by":
        # Cruza la zona en ~1.2 s: por debajo del umbral de 2 s
        n = max(2, int(1.2 * fps))
        for i in range(n):
            poner(cx - 40 + i * (80 / n), cy)
        eventos_esperados.append({"zone_id": zona.zone_id, "event_type": "pass_by"})
        for i in range(8):
            poner(cx + 60 + i * 15, y_pasillo)
        return {"person_id": person_id, "frames": frames, "esperados": eventos_esperados}

    # Se detiene frente a la gondola
    quieto = int(rng.uniform(2.5, 4.0) * fps)
    for _ in range(quieto):
        poner(cx, cy)
    eventos_esperados.append({"zone_id": zona.zone_id, "event_type": "approach"})

    if escenario in ("pickup", "pickup_return"):
        # Primer alcance: ~0.9 s con el bbox ensanchado
        for _ in range(max(2, int(0.9 * fps))):
            poner(cx, cy, ancho=ANCHO_PERSONA * factor_alcance)
        for _ in range(int(1.2 * fps)):
            poner(cx, cy)
        eventos_esperados.append({"zone_id": zona.zone_id, "event_type": "pickup"})

    if escenario == "pickup_return":
        # Lo mira un momento y lo devuelve al estante
        for _ in range(int(1.5 * fps)):
            poner(cx, cy)
        for _ in range(max(2, int(0.8 * fps))):
            poner(cx, cy, ancho=ANCHO_PERSONA * factor_alcance)
        for _ in range(int(1.0 * fps)):
            poner(cx, cy)
        eventos_esperados.append({"zone_id": zona.zone_id, "event_type": "return"})
    elif escenario == "pickup":
        eventos_esperados.append({"zone_id": zona.zone_id, "event_type": "takeaway"})

    # Se retira hacia el pasillo
    for i in range(10):
        poner(cx + 20 + i * 14, y_pasillo)

    return {"person_id": person_id, "frames": frames, "esperados": eventos_esperados}


def simular(
    layout,
    n_personas: int,
    fps: float,
    seed: int,
    oclusiones: bool,
    factor_alcance: float = FACTOR_ALCANCE,
    ruido_px: float = RUIDO_PX,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rng = random.Random(seed)

    gondolas = layout.gondolas
    if not gondolas:
        raise SystemExit("El layout no tiene zonas de gondola")
    pasillo = next(
        (z for z in layout if not z.es_gondola), gondolas[0]
    )

    planes = []
    ground_truth: dict[str, Any] = {"personas": []}

    for pid in range(1, n_personas + 1):
        escenario = rng.choices(ESCENARIOS, weights=PESOS, k=1)[0]
        zona = rng.choice(gondolas) if escenario != "pasillo" else None
        inicio = rng.randint(0, int(60 * fps))
        plan = _plan_persona(
            pid, escenario, zona, pasillo, inicio, fps, rng,
            factor_alcance=factor_alcance, ruido_px=ruido_px,
        )

        if oclusiones and plan["frames"] and rng.random() < 0.35:
            # Elimina 1-2 frames intermedios: simula la perdida momentanea del
            # track por oclusion. La ventana de gracia debe absorberla.
            n = len(plan["frames"])
            corte = rng.randint(n // 3, max(n // 3 + 1, 2 * n // 3))
            del plan["frames"][corte : corte + rng.randint(1, 2)]

        planes.append(plan)
        ground_truth["personas"].append(
            {
                "track_id": str(pid),
                "escenario": escenario,
                "zone_id": zona.zone_id if zona else None,
                "eventos_esperados": plan["esperados"],
            }
        )

    # Reagrupa por frame
    por_frame: dict[int, list[dict[str, Any]]] = {}
    for plan in planes:
        for frame_id, bbox in plan["frames"]:
            por_frame.setdefault(frame_id, []).append(
                {"person_id": plan["person_id"], "bbox": bbox, "class": "person"}
            )

    salida = []
    if por_frame:
        for frame_id in range(0, max(por_frame) + 1):
            salida.append(
                {
                    "frame_id": frame_id,
                    "timestamp_ms": round(frame_id * 1000.0 / fps, 2),
                    "tracks": por_frame.get(frame_id, []),
                }
            )

    ground_truth["meta"] = {
        "fps": fps,
        "seed": seed,
        "personas": n_personas,
        "frames": len(salida),
        "oclusiones_simuladas": oclusiones,
        "factor_alcance": factor_alcance,
        "ruido_px": ruido_px,
    }
    return salida, ground_truth


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Genera tracking.jsonl sintetico con comportamientos conocidos"
    )
    parser.add_argument("--zonas", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--personas", type=int, default=24)
    parser.add_argument("--fps", type=float, default=10.0)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument(
        "--factor-alcance",
        type=float,
        default=FACTOR_ALCANCE,
        help="cuanto ensancha el bbox el brazo extendido (1.42 = gesto claro; "
             "bajarlo a 1.20 simula un gesto sutil o una camara mal ubicada)",
    )
    parser.add_argument(
        "--ruido",
        type=float,
        default=RUIDO_PX,
        help="jitter del detector en pixeles (default: 0.6)",
    )
    parser.add_argument(
        "--sin-oclusiones",
        action="store_true",
        help="no simular perdidas momentaneas del track",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    layout = cargar_layout(args.zonas)

    frames, ground_truth = simular(
        layout,
        n_personas=args.personas,
        fps=args.fps,
        seed=args.seed,
        oclusiones=not args.sin_oclusiones,
        factor_alcance=args.factor_alcance,
        ruido_px=args.ruido,
    )

    salida = Path(args.output)
    salida.parent.mkdir(parents=True, exist_ok=True)
    with salida.open("w", encoding="utf-8") as fh:
        for frame in frames:
            fh.write(json.dumps(frame, ensure_ascii=False) + "\n")

    ruta_gt = salida.with_name(salida.stem + "_ground_truth.json")
    ruta_gt.write_text(
        json.dumps(ground_truth, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    conteo: dict[str, int] = {}
    for persona in ground_truth["personas"]:
        conteo[persona["escenario"]] = conteo.get(persona["escenario"], 0) + 1

    print(f"[ok] Frames generados: {len(frames)} @ {args.fps} fps")
    print(f"[ok] Personas: {args.personas}")
    for escenario, n in sorted(conteo.items()):
        print(f"[ok]   {escenario}: {n}")
    print(f"[ok] Tracking sintetico: {salida}")
    print(f"[ok] Ground truth: {ruta_gt}")


if __name__ == "__main__":
    main()
