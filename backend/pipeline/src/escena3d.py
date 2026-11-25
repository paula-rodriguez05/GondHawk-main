"""
escena3d.py
Generador de video sintético 3D de tienda — GondHawk.

Sustituye al renderizador 2.5D: la tienda y las personas son geometría real en
tres dimensiones, proyectada por una cámara en perspectiva. El ground truth se
obtiene proyectando la malla completa de cada persona, así que el bounding box
es exacto por construcción y no una aproximación dibujada.

Por qué importa que sea 3D
--------------------------
El generador anterior dibujaba figuras planas y YOLO no las reconocía: 1.257
detecciones donde debía haber unas 8.000. Un detector entrenado sobre
fotografías responde a volumen, sombreado, sombra proyectada y proporción, no
a siluetas de líneas. Con geometría 3D sombreada esas señales existen.

Sigue sin ser fotorrealismo: no hay trazado de rayos, texturas fotográficas ni
oclusión ambiental. Es la diferencia entre "el detector puede reconocerlo" y
"el detector no distingue esto de una foto", y sólo se pretende lo primero.

Privacidad
----------
Ninguna persona real es grabada, así que no hay dato personal que tratar ni
consentimiento que recabar. Y como el generador decide qué hace cada persona,
la verdad de fondo es exacta: se puede medir precisión y recall de la detección
de eventos, cosa imposible con video real sin anotarlo a mano.

Densidad de personas
--------------------
La relación entre `--personas` y `--duracion` importa más de lo que parece.
Medido sobre esta escena, con 12 personas repartidas en:

    20 s  -> 6.9 personas en pantalla, 4.8 pares de bboxes solapados
    60 s  -> 2.7 personas en pantalla, 0.7 pares solapados
    120 s -> 1.4 personas en pantalla, 0.1 pares solapados

Cuando varias personas se agolpan frente al mismo lineal, sus siluetas se
solapan desde la cámara y el detector devuelve UNA caja para el grupo: se
pierde la mitad de las personas y aparecen bboxes mayores que cualquier
persona real. Como referencia, unos 5 segundos de video por persona mantienen
la escena legible. La aglomeración degrada la detección igual en una tienda
real un sábado por la tarde: es una limitación del enfoque, no del generador.

Uso
---
    python pipeline/src/escena3d.py \\
        --output pipeline/uploads/tienda3d.mp4 \\
        --duracion 90 --personas 16 --seed 7
"""

from __future__ import annotations

import argparse
import json
import math
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from humanoide3d import Humanoide, Pose
from render3d import Camara, Malla, Renderer, caja

# Colores en BGR
PISO = (152, 152, 156)
PARED = (186, 182, 174)
ESTRUCTURA = (86, 84, 82)
ENTREPANO = (128, 126, 122)


@dataclass
class GondolaZ:
    """
    Góndola en el mundo 3D.

    `x_centro` y `z` la ubican en planta; `frente` indica hacia qué lado mira
    (−1 hacia la cámara, +1 en contra), lo que determina de qué lado se paran
    los compradores.
    """

    zone_id: str
    x_centro: float
    z: float
    ancho: float
    alto: float = 1.85
    fondo: float = 0.55
    frente: int = -1

    def z_banda(self) -> float:
        """Profundidad a la que se para una persona frente a este estante."""
        return self.z + self.frente * (self.fondo / 2 + 0.55)

    def mallas(self, rng: random.Random) -> list[Malla]:
        partes: list[Malla] = []

        # Estructura
        partes.append(
            caja(self.ancho, self.alto, self.fondo, ESTRUCTURA).transformar(
                None, np.array([self.x_centro, self.alto / 2, self.z])
            )
        )

        # Entrepaños con producto. El producto son cajas de colores saturados:
        # es la señal que usan el verificador de escena y la propuesta
        # automática de zonas, así que tiene que existir en el mundo 3D.
        n_niveles = 4
        for nivel in range(n_niveles):
            y = 0.35 + nivel * (self.alto - 0.5) / n_niveles
            partes.append(
                caja(self.ancho - 0.06, 0.04, self.fondo * 0.92, ENTREPANO).transformar(
                    None, np.array([self.x_centro, y, self.z])
                )
            )

            ancho_prod = 0.13
            n = int((self.ancho - 0.18) / (ancho_prod + 0.03))
            for i in range(n):
                x = self.x_centro - self.ancho / 2 + 0.12 + i * (ancho_prod + 0.03)
                color = tuple(int(v) for v in rng.choices(range(35, 250), k=3))
                alto_prod = rng.uniform(0.16, 0.26)
                partes.append(
                    caja(ancho_prod, alto_prod, self.fondo * 0.55, color, brillo=0.12)
                    .transformar(
                        None,
                        np.array([
                            x, y + alto_prod / 2 + 0.02,
                            self.z + self.frente * self.fondo * 0.12,
                        ]),
                    )
                )

        return partes


@dataclass
class PersonaZ:
    """Guion de una persona en el mundo 3D."""

    pid: int
    escenario: str
    gondola: GondolaZ | None
    humanoide: Humanoide
    frame_entrada: int
    velocidad: float
    desde_izquierda: bool
    eventos_esperados: list[dict[str, Any]] = field(default_factory=list)
    guion: list[dict[str, Any]] = field(default_factory=list)


class Tienda3D:
    """Sala de ventas: piso, paredes y dos hileras de góndolas."""

    ESPACIADO_X = 3.1

    def __init__(self, rng: random.Random, n_gondolas: int = 3):
        self.rng = rng
        # Góndolas repartidas simétricamente sobre el eje X, con el mismo
        # espaciado que antes se hardcodeaba para 3. Antes el número de
        # góndolas del mundo 3D era fijo sin importar lo que pidiera quien
        # generaba la escena; ahora escala con `n_gondolas`.
        centro = (n_gondolas - 1) / 2
        self.gondolas = [
            GondolaZ(f"gondola_A{i + 1}", (i - centro) * self.ESPACIADO_X, 4.2, 2.5, frente=-1)
            for i in range(n_gondolas)
        ]
        self._estaticas = self._construir()

    def _construir(self) -> list[Malla]:
        partes = [
            caja(24.0, 0.08, 24.0, PISO).transformar(None, np.array([0.0, -0.04, 4.0])),
            caja(24.0, 4.0, 0.2, PARED).transformar(None, np.array([0.0, 2.0, 9.0])),
        ]
        for g in self.gondolas:
            partes.extend(g.mallas(self.rng))
        return partes

    @property
    def estaticas(self) -> list[Malla]:
        return self._estaticas


class GeneradorEscena3D:
    ESCENARIOS = ["pasa_de_largo", "se_detiene", "toma", "toma_y_devuelve"]
    PESOS = [0.24, 0.20, 0.30, 0.26]

    def __init__(
        self,
        ancho: int = 960,
        alto: int = 540,
        fps: int = 15,
        duracion_s: int = 90,
        n_personas: int = 16,
        n_gondolas: int = 3,
        seed: int = 7,
    ):
        self.rng = random.Random(seed)
        self.fps = fps
        self.total_frames = fps * duracion_s
        self.n_personas = n_personas
        self.seed = seed

        self.tienda = Tienda3D(self.rng, n_gondolas=n_gondolas)
        # Cámara de techo mirando el lineal, como una de seguridad real.
        self.camara = Camara(
            posicion=np.array([0.0, 3.1, -3.4]),
            objetivo=np.array([0.0, 1.15, 4.0]),
            fov_grados=62.0, ancho=ancho, alto=alto,
        )
        self.renderer = Renderer(self.camara, ambiental=0.46)

    # -- Guiones ----------------------------------------------------------

    def _crear_personas(self) -> list[PersonaZ]:
        personas = []
        for pid in range(1, self.n_personas + 1):
            escenario = self.rng.choices(self.ESCENARIOS, weights=self.PESOS, k=1)[0]
            gondola = (
                None if escenario == "pasa_de_largo"
                else self.rng.choice(self.tienda.gondolas)
            )
            personas.append(
                PersonaZ(
                    pid=pid,
                    escenario=escenario,
                    gondola=gondola,
                    humanoide=Humanoide(
                        altura=self.rng.uniform(1.58, 1.86),
                        corpulencia=self.rng.uniform(0.88, 1.18),
                        rng=self.rng,
                    ),
                    frame_entrada=self.rng.randint(0, max(1, self.total_frames - 220)),
                    velocidad=self.rng.uniform(0.055, 0.095),  # metros por frame
                    desde_izquierda=self.rng.random() < 0.5,
                )
            )
        return personas

    def _construir_guion(self, p: PersonaZ) -> None:
        direccion = 1 if p.desde_izquierda else -1
        x = -7.5 if p.desde_izquierda else 7.5
        f = p.frame_entrada
        fase = self.rng.uniform(0, 6.28)

        def paso(x_pos: float, z: float, alcance: float = 0.0, quieto: bool = False) -> None:
            nonlocal f, fase
            # La fase de marcha solo avanza si la persona se desplaza: quien
            # está parado frente al estante no mueve las piernas.
            if not quieto:
                fase += 0.42
            p.guion.append({
                "frame": f, "x": x_pos, "z": z,
                "alcance": alcance, "fase": fase,
                "giro": (math.pi / 2 if direccion > 0 else -math.pi / 2) if not quieto else 0.0,
            })
            f += 1

        if p.escenario == "pasa_de_largo" or p.gondola is None:
            # Camina por el pasillo delantero, sin acercarse al lineal.
            z_paso = 1.9 + self.rng.uniform(-0.30, 0.30)
            while -8.0 < x < 8.0:
                paso(x, z_paso)
                x += direccion * p.velocidad
            return

        g = p.gondola

        # Cada persona se para en un punto propio del lineal, no todas en el
        # centro. Con todas en g.x_centro, dos visitantes simultáneos quedaban
        # superpuestos desde la cámara: el detector devolvía UNA sola caja para
        # el grupo (bboxes mayores que cualquier persona real) y se perdía la
        # mitad de las personas. La dispersión en z evita el mismo solape entre
        # quien está delante y quien está detrás.
        x_parada = g.x_centro + self.rng.uniform(-g.ancho * 0.34, g.ancho * 0.34)
        z_banda = g.z_banda() + self.rng.uniform(-0.12, 0.12)
        z_paso = 1.9 + self.rng.uniform(-0.15, 0.15)

        # 1. Camina por el pasillo hasta quedar a la altura de su punto
        while (direccion > 0 and x < x_parada) or (direccion < 0 and x > x_parada):
            paso(x, z_paso)
            x += direccion * p.velocidad
            if f - p.frame_entrada > self.total_frames:
                return

        # 2. Se aproxima al lineal
        z = z_paso
        while z < z_banda:
            paso(x_parada, z)
            z = min(z + 0.05, z_banda)

        # 3. Se detiene, mirando al estante
        quieto_frames = int(self.rng.uniform(3.2, 5.0) * self.fps)
        for _ in range(quieto_frames):
            paso(x_parada, z_banda, quieto=True)
        p.eventos_esperados.append({"zone_id": g.zone_id, "event_type": "approach"})

        def alcanzar() -> None:
            """Sube el brazo, lo sostiene y lo baja."""
            subida = max(3, int(0.40 * self.fps))
            sostener = max(3, int(0.55 * self.fps))
            for i in range(subida):
                paso(x_parada, z_banda, alcance=i / subida, quieto=True)
            for _ in range(sostener):
                paso(x_parada, z_banda, alcance=1.0, quieto=True)
            for i in range(subida):
                paso(x_parada, z_banda, alcance=1.0 - i / subida, quieto=True)

        if p.escenario in ("toma", "toma_y_devuelve"):
            alcanzar()
            for _ in range(int(1.5 * self.fps)):
                paso(x_parada, z_banda, quieto=True)
            p.eventos_esperados.append({"zone_id": g.zone_id, "event_type": "pickup"})

        if p.escenario == "toma_y_devuelve":
            for _ in range(int(1.6 * self.fps)):
                paso(x_parada, z_banda, quieto=True)
            alcanzar()
            for _ in range(int(1.2 * self.fps)):
                paso(x_parada, z_banda, quieto=True)
            p.eventos_esperados.append({"zone_id": g.zone_id, "event_type": "return"})
        elif p.escenario == "toma":
            p.eventos_esperados.append({"zone_id": g.zone_id, "event_type": "takeaway"})

        # 4. Se retira
        while z > z_paso:
            paso(x_parada, z)
            z -= 0.05
        while -8.0 < x < 8.0:
            paso(x, z_paso)
            x += direccion * p.velocidad

    # -- Zonas -------------------------------------------------------------

    def zonas_json(self, muestras_por_gondola: int = 24) -> dict[str, Any]:
        """
        Deriva las zonas de análisis proyectando el mundo 3D a la imagen.

        Ésta es la ventaja decisiva de trabajar en 3D: la zona no se dibuja a
        ojo sobre un frame, se calcula. Se coloca un humanoide de referencia en
        varias posiciones de la banda de interacción, se proyecta su bounding
        box y se toma la envolvente de los CENTROIDES.

        El centroide es lo que importa porque el módulo 1 ubica a la persona
        por el centro de su caja, no por los pies. Una zona dibujada sobre el
        piso frente al mueble captura a quien pasa por detrás y pierde a quien
        se detiene delante — el error que mantuvo el embudo en cero durante
        todas las pruebas con video real.
        """
        referencia = Humanoide(altura=1.72, rng=random.Random(0))
        zonas = []

        for g in self.tienda.gondolas:
            centroides = []
            for i in range(muestras_por_gondola):
                t = i / max(1, muestras_por_gondola - 1)
                x = g.x_centro - g.ancho * 0.42 + t * g.ancho * 0.84
                for dz in (-0.18, 0.0, 0.18):
                    malla = referencia.malla_unida(
                        np.array([x, 0.0, g.z_banda() + dz]), Pose()
                    )
                    bbox = self.renderer.bbox_de(malla)
                    if bbox:
                        centroides.append((
                            (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2,
                        ))

            if not centroides:
                continue

            xs = [c[0] for c in centroides]
            ys = [c[1] for c in centroides]
            margen_x, margen_y = 26, 30
            zonas.append({
                "zone_id": g.zone_id,
                "poligono": [
                    [int(min(xs) - margen_x), int(min(ys) - margen_y)],
                    [int(max(xs) + margen_x), int(min(ys) - margen_y)],
                    [int(max(xs) + margen_x), int(max(ys) + margen_y)],
                    [int(min(xs) - margen_x), int(max(ys) + margen_y)],
                ],
                "es_gondola": True,
            })

        # Pasillo: misma técnica sobre la línea de paso
        centroides = []
        for i in range(40):
            x = -6.0 + i * 0.3
            malla = referencia.malla_unida(np.array([x, 0.0, 1.9]), Pose())
            bbox = self.renderer.bbox_de(malla)
            if bbox:
                centroides.append(((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2))
        if centroides:
            ys = [c[1] for c in centroides]
            zonas.append({
                "zone_id": "pasillo_central",
                "poligono": [
                    [0, int(min(ys) - 34)],
                    [self.camara.ancho - 1, int(min(ys) - 34)],
                    [self.camara.ancho - 1, int(max(ys) + 34)],
                    [0, int(max(ys) + 34)],
                ],
                "es_gondola": False,
            })

        return {
            "video_ref": "escena3d",
            "frame_width": self.camara.ancho,
            "frame_height": self.camara.alto,
            "zonas": zonas,
            "_origen": (
                "Zonas derivadas por proyección del mundo 3D: envolvente de los "
                "centroides de una persona de referencia parada en la banda de "
                "interacción. No dibujadas a mano."
            ),
        }

    # -- Render ------------------------------------------------------------

    def _abrir_writer(self, ruta: Path) -> tuple[cv2.VideoWriter, str]:
        """
        Abre el escritor en mp4v y deja la conversión a H.264 para el final.

        Sondear códecs no sirve: con avc1, isOpened() devuelve True aunque el
        codificador de H.264 no se haya cargado, y se pueden perder todos los
        frames renderizados sin ningún error visible.
        """
        writer = cv2.VideoWriter(
            str(ruta), cv2.VideoWriter_fourcc(*"mp4v"),
            self.fps, (self.camara.ancho, self.camara.alto),
        )
        if not writer.isOpened():
            raise RuntimeError(f"No se pudo abrir el escritor de video en {ruta}")
        return writer, "mp4v"

    def _convertir_a_h264(self, ruta: Path) -> None:
        """
        Reescribe el video en H.264 para que se reproduzca en el navegador.

        Falla en silencio: no poder convertir deja el video sin reproducirse en
        el tablero, pero no debe invalidar un render que ya terminó.
        """
        if not ruta.exists() or ruta.stat().st_size < 1024:
            return

        try:
            import subprocess

            import imageio_ffmpeg
        except ImportError:
            print("[aviso] pip install imageio-ffmpeg para reproducir el video en el tablero.")
            return

        temporal = ruta.with_name(ruta.stem + "_h264.mp4")
        try:
            resultado = subprocess.run(
                [
                    imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error",
                    "-i", str(ruta),
                    "-vcodec", "libx264", "-pix_fmt", "yuv420p",
                    str(temporal),
                ],
                capture_output=True, timeout=900,
            )
            if (
                resultado.returncode == 0
                and temporal.exists()
                and temporal.stat().st_size > 1024
            ):
                temporal.replace(ruta)
                print("[video] Convertido a H.264.")
            else:
                temporal.unlink(missing_ok=True)
        except Exception as exc:
            print(f"[aviso] No se pudo convertir a H.264: {exc}")
            temporal.unlink(missing_ok=True)

    def generar(self, ruta_video: Path) -> dict[str, Any]:
        personas = self._crear_personas()
        for p in personas:
            self._construir_guion(p)

        por_frame: dict[int, list[tuple[PersonaZ, dict]]] = {}
        for p in personas:
            for punto in p.guion:
                por_frame.setdefault(punto["frame"], []).append((p, punto))

        ruta_video = Path(ruta_video)
        ruta_video.parent.mkdir(parents=True, exist_ok=True)
        writer, codec = self._abrir_writer(ruta_video)
        print(f"[render] Códec: {codec}")
        if codec == "mp4v":
            print("[aviso] mp4v no se reproduce en navegadores; conviértelo para el tablero.")

        anotaciones: dict[int, list[dict]] = {}
        estaticas = self.tienda.estaticas

        try:
            for frame_id in range(self.total_frames):
                mallas = list(estaticas)

                for persona, punto in por_frame.get(frame_id, []):
                    pose = Pose(
                        fase_paso=punto["fase"],
                        alcance=punto["alcance"],
                        alcance_derecho=True,
                        giro_cuerpo=punto["giro"],
                    )
                    posicion = np.array([punto["x"], 0.0, punto["z"]])
                    mallas.extend(persona.humanoide.mallas(posicion, pose))

                    # Ground truth: bbox exacto de la malla completa proyectada
                    bbox = self.renderer.bbox_de(
                        persona.humanoide.malla_unida(posicion, pose)
                    )
                    if bbox and bbox[2] - bbox[0] > 4 and bbox[3] - bbox[1] > 8:
                        anotaciones.setdefault(frame_id, []).append({
                            "person_id": persona.pid,
                            "bbox": list(bbox),
                            "class": "person",
                        })

                img = self.renderer.render(mallas)

                # Ruido de sensor: sin él la imagen es demasiado limpia y no
                # ejercita la robustez del detector.
                ruido = np.random.normal(0, 3.0, img.shape).astype(np.int16)
                img = np.clip(img.astype(np.int16) + ruido, 0, 255).astype(np.uint8)

                writer.write(img)
                if frame_id % 100 == 0:
                    print(f"[render] frame {frame_id}/{self.total_frames}")
        finally:
            writer.release()
            self._convertir_a_h264(ruta_video)

        conteo: dict[str, int] = {}
        for p in personas:
            conteo[p.escenario] = conteo.get(p.escenario, 0) + 1

        ground_truth = {
            "meta": {
                "video": ruta_video.name,
                "fps": self.fps,
                "frames": self.total_frames,
                "resolucion": [self.camara.ancho, self.camara.alto],
                "personas": len(personas),
                "seed": self.seed,
                "escenarios": conteo,
                "render": "3D por software: geometría, cámara en perspectiva, sombreado y sombras.",
                "naturaleza": (
                    "Escena sintética. Ninguna persona real fue grabada, por lo "
                    "que no hay dato personal que tratar. La verdad de fondo es "
                    "exacta por construcción."
                ),
            },
            "personas": [
                {
                    "track_id": str(p.pid),
                    "escenario": p.escenario,
                    "zone_id": p.gondola.zone_id if p.gondola else None,
                    "eventos_esperados": p.eventos_esperados,
                }
                for p in personas
            ],
        }

        base = ruta_video.with_suffix("")
        Path(f"{base}_ground_truth.json").write_text(
            json.dumps(ground_truth, ensure_ascii=False, indent=2), encoding="utf-8")
        Path(f"{base}_zonas.json").write_text(
            json.dumps(self.zonas_json(), ensure_ascii=False, indent=2), encoding="utf-8")
        with Path(f"{base}_detecciones_ideales.jsonl").open("w", encoding="utf-8") as fh:
            for frame_id in range(self.total_frames):
                fh.write(json.dumps({
                    "frame_id": frame_id,
                    "timestamp_ms": round(frame_id * 1000.0 / self.fps, 2),
                    "tracks": anotaciones.get(frame_id, []),
                }, ensure_ascii=False) + "\n")

        return ground_truth


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Genera video sintético 3D de tienda con ground truth exacto")
    parser.add_argument("--output", default="pipeline/uploads/tienda3d.mp4")
    parser.add_argument("--ancho", type=int, default=960)
    parser.add_argument("--alto", type=int, default=540)
    parser.add_argument("--fps", type=int, default=15)
    parser.add_argument("--duracion", type=int, default=90, help="segundos")
    parser.add_argument(
        "--personas", type=int, default=16,
        help=(
            "Número de personas en todo el video. Densidades altas provocan "
            "oclusión entre personas y el detector las fusiona: calcula unos "
            "5 segundos de duración por persona."
        ),
    )
    parser.add_argument(
        "--gondolas", type=int, default=3, help="Número de góndolas del mundo 3D",
    )
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    generador = GeneradorEscena3D(
        ancho=args.ancho, alto=args.alto, fps=args.fps,
        duracion_s=args.duracion, n_personas=args.personas,
        n_gondolas=args.gondolas, seed=args.seed,
    )
    segundos_por_persona = args.duracion / max(1, args.personas)
    if segundos_por_persona < 4.0:
        print(
            f"[aviso] Densidad alta: {segundos_por_persona:.1f} s por persona. "
            "Las personas van a solaparse frente al lineal y el detector "
            "fusionará sus cajas. Sube --duracion o baja --personas."
        )

    gt = generador.generar(Path(args.output))
    base = Path(args.output).with_suffix("")

    print(f"\n[ok] Video 3D: {args.output}")
    print(f"[ok] {gt['meta']['frames']} frames @ {args.fps} fps")
    print(f"[ok] Personas: {gt['meta']['personas']}")
    for escenario, n in sorted(gt["meta"]["escenarios"].items()):
        print(f"[ok]   {escenario}: {n}")

    esperados: dict[str, int] = {}
    for persona in gt["personas"]:
        for ev in persona["eventos_esperados"]:
            esperados[ev["event_type"]] = esperados.get(ev["event_type"], 0) + 1
    print("[ok] Eventos esperados:")
    for tipo, n in sorted(esperados.items()):
        print(f"[ok]   {tipo}: {n}")

    print(f"[ok] Ground truth: {base}_ground_truth.json")
    print(f"[ok] Zonas derivadas del 3D: {base}_zonas.json")
    print(f"[ok] Detecciones ideales: {base}_detecciones_ideales.jsonl")
    print("\n[!] Ninguna persona real fue grabada.")


if __name__ == "__main__":
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    main()