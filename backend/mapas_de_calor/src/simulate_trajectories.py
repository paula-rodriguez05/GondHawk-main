"""
simulate_trajectories.py — Genera un JSONL de trayectorias FALSAS con el MISMO formato
que entrega el modulo de tracking real de Juan (person_id entero, bbox/centroid),
para poder desarrollar y probar el heatmap sin depender de que exista todavia
el output real de deteccion + tracking.

v3 — adaptado al formato real de Juan (PR #3):
  1. Emite `person_id` ENTERO (no "t_0001" ni hex), exactamente como el
     BYTETracker de Juan. El lector de este modulo lo normaliza a str.
  2. Simulacion zone-aware: las personas entran por el borde inferior, cruzan
     el pasillo central y algunas se desvian a una gondola con permanencia
     (dwell), para que el heatmap muestre zonas calientes/frias creibles.
  3. --fps parametrizado (por defecto 10, el fps real de vtest.avi).

Uso:
    python src/simulate_trajectories.py --output data/tracking_simulado.jsonl \
        --zonas config/zonas.json --frames 800 --personas 15 --fps 10 --seed 42
"""
import argparse
import json
import math
import random
from pathlib import Path


def _centro_poligono(poligono) -> tuple:
    xs = [p[0] for p in poligono]
    ys = [p[1] for p in poligono]
    return (sum(xs) / len(xs), sum(ys) / len(ys))


def _punto_dentro(poligono, rng: random.Random) -> tuple:
    """Punto cerca del centro del poligono con jitter (suficiente para poligonos
    convexos como los rectangulos de las zonas)."""
    cx, cy = _centro_poligono(poligono)
    xs = [p[0] for p in poligono]
    ys = [p[1] for p in poligono]
    jx = min((max(xs) - min(xs)) / 4.0, 30.0)
    jy = min((max(ys) - min(ys)) / 4.0, 30.0)
    return (cx + rng.uniform(-jx, jx), cy + rng.uniform(-jy, jy))


class _Persona:
    """State machine simple: sigue waypoints; en la gondola se queda quieta (dwell)."""

    def __init__(self, person_id: int, start_frame: int, waypoints: list, dwell_frames: int):
        self.person_id = person_id
        self.start = start_frame
        self.waypoints = waypoints
        self.idx = 0
        self.x, self.y = waypoints[0]
        self.speed = random.Random(person_id).uniform(1.8, 3.2)  # px/frame estable por persona
        self.dwell_restante = dwell_frames

    def step(self, rng: random.Random, width: int, height: int):
        if self.dwell_restante > 0:
            # permanencia frente a la gondola: jitter pequeno alrededor del punto
            self.x += rng.uniform(-0.8, 0.8)
            self.y += rng.uniform(-0.8, 0.8)
            self.dwell_restante -= 1
            return

        if self.idx >= len(self.waypoints) - 1:
            return  # sin mas destinos: desaparece del frame

        tx, ty = self.waypoints[self.idx + 1]
        dx, dy = tx - self.x, ty - self.y
        dist = math.hypot(dx, dy)
        if dist <= self.speed:
            self.x, self.y = tx, ty
            self.idx += 1
        else:
            self.x += dx / dist * self.speed + rng.uniform(-0.5, 0.5)
            self.y += dy / dist * self.speed + rng.uniform(-0.5, 0.5)

        self.x = min(max(self.x, 0), width)
        self.y = min(max(self.y, 0), height)


def _construir_persona(rng: random.Random, person_id: int, start: int,
                       zonas_por_id: dict, pasillo_id, gondolas: list,
                       width: int, height: int, prob_gondola: float) -> _Persona:
    # entra por el borde inferior
    waypoints = [(rng.uniform(0, width), height - 10)]

    punto_pasillo = None
    if pasillo_id is not None:
        poly = zonas_por_id[pasillo_id]
        punto_pasillo = (rng.uniform(min(p[0] for p in poly),
                                     max(p[0] for p in poly)),
                         _punto_dentro(poly, rng)[1])
        waypoints.append(punto_pasillo)

    dwell_frames = 0
    va_a_gondola = gondolas and rng.random() < prob_gondola
    if va_a_gondola:
        zona = zonas_por_id[rng.choice(gondolas)]
        waypoints.append(_punto_dentro(zona, rng))
        dwell_frames = rng.randint(20, 80)  # 2-8 s a 10 fps
        if punto_pasillo is not None:
            waypoints.append(punto_pasillo)  # vuelve al pasillo

    # sale por el borde superior
    waypoints.append((rng.uniform(0, width), -10))

    return _Persona(person_id, start, waypoints, dwell_frames)


def simulate(output_path: str, n_frames: int, n_personas: int, width: int, height: int,
             seed: int, fps: float, zonas_path: str = None, prob_gondola: float = 0.6):
    rng = random.Random(seed)

    zonas_por_id, pasillo_id, gondolas = {}, None, []
    if zonas_path:
        with open(zonas_path, "r", encoding="utf-8") as f:
            zonas_data = json.load(f)
        zonas_por_id = {z["zone_id"]: z["poligono"] for z in zonas_data["zonas"]}
        pasillo_id = next((zid for zid in zonas_por_id if "pasillo" in zid.lower()), None)
        gondolas = [zid for zid in zonas_por_id if zid != pasillo_id]
        print(f"[info] simulacion zone-aware: {len(gondolas)} gondolas, "
              f"pasillo={pasillo_id or 'no definido'}, prob. desvio a gondola={prob_gondola}")
    else:
        print("[info] sin --zonas: random walk uniforme (el heatmap saldra difuso)")

    personas = []
    for i in range(n_personas):
        start = rng.randint(0, max(0, n_frames - 50))
        personas.append(_construir_persona(
            rng, i + 1, start,  # person_id entero, como Juan (empieza en 1)
            zonas_por_id, pasillo_id, gondolas, width, height, prob_gondola,
        ))

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    ms_por_frame = 1000.0 / fps
    with open(output_path, "w", encoding="utf-8") as f:
        for frame_id in range(n_frames):
            tracks = []
            for p in personas:
                if frame_id < p.start:
                    continue
                p.step(rng, width, height)
                if p.idx >= len(p.waypoints) - 1 and p.dwell_restante <= 0:
                    continue  # ya salio del frame
                tracks.append({
                    "person_id": p.person_id,
                    "centroid": [round(p.x, 1), round(p.y, 1)],
                })
            record = {
                "frame_id": frame_id,
                "timestamp_ms": round(frame_id * ms_por_frame, 1),
                "tracks": tracks,
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"Trayectorias simuladas guardadas en {output_path} "
          f"({n_frames} frames, {n_personas} personas, fps={fps}, seed={seed}).")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="data/tracking_simulado.jsonl")
    parser.add_argument("--zonas", default="config/zonas.json",
                        help="JSON de zonas para simulacion zone-aware (pasar '' para random walk)")
    parser.add_argument("--frames", type=int, default=800)
    parser.add_argument("--personas", type=int, default=15)
    parser.add_argument("--width", type=int, default=768)
    parser.add_argument("--height", type=int, default=576)
    parser.add_argument("--fps", type=float, default=10.0,
                        help="fps del video de referencia (vtest.avi = 10)")
    parser.add_argument("--prob-gondola", type=float, default=0.6,
                        help="probabilidad de que una persona se desvie a una gondola")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    simulate(args.output, args.frames, args.personas, args.width, args.height,
             args.seed, args.fps, args.zonas or None, args.prob_gondola)


if __name__ == "__main__":
    main()
