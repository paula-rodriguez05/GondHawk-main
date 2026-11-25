"""
escena_sintetica.py
Generador de video sintético de tienda — GondHawk.

Produce video de una superficie comercial con personas caminando, deteniéndose
frente a las góndolas, tomando productos y devolviéndolos al estante. Junto al
video escribe el **ground truth exacto**: qué hizo cada persona, en qué zona y
en qué momento.

Por qué existe
--------------
Probar un sistema de análisis de comportamiento en retail exige video de gente
real en una tienda, lo que arrastra tres problemas: consentimiento informado de
cada persona grabada, tratamiento de dato personal bajo la Ley 1581, y la
imposibilidad de saber la verdad de fondo (nadie anota cuántas veces alguien
tomó y devolvió un producto).

Los tres desaparecen con escenas sintéticas. Nadie fue grabado, así que no hay
dato personal que proteger, y como el generador *decide* qué hace cada persona,
la verdad de fondo es exacta por construcción. Eso permite medir precisión y
recall de la detección de eventos, que es un criterio explícito del reto y no
se puede calcular con video real sin anotarlo a mano.

Es el enfoque *sim-to-real* que se usa en robótica: entrenar y validar en
simulación, desplegar en el mundo. Aquí se usa para validar.

Qué es y qué no es
------------------
Es un renderizador 2.5D: dibuja la escena con perspectiva, figuras humanas
articuladas con brazos que se extienden hacia el estante, y variación de
escala, color e iluminación. NO es un motor 3D con avatares fotorrealistas.

Esa distinción hay que sostenerla al presentarlo. Sirve para validar la
LÓGICA del sistema —geometría, zonas, máquina de estados, tasas— con verdad
conocida. No sustituye video real para validar el DETECTOR de personas, que
aprendió de fotografías y responde distinto ante una figura dibujada.

Uso
---
    python pipeline/src/escena_sintetica.py \\
        --output pipeline/uploads/tienda_sintetica.mp4 \\
        --duracion 120 --personas 18 --seed 7

Luego se analiza como cualquier otro video y se mide la exactitud:

    python pipeline/src/pipeline.py --video pipeline/uploads/tienda_sintetica.mp4 \\
        --zonas pipeline/uploads/tienda_sintetica_zonas.json --outdir pipeline/output

    python deteccion_eventos/tools/evaluar_exactitud.py \\
        --eventos pipeline/output/eventos_interaccion.jsonl \\
        --ground-truth pipeline/uploads/tienda_sintetica_ground_truth.json
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

# ── Paleta de la escena ─────────────────────────────────────────────────────

PISO = (168, 168, 172)
PARED = (196, 194, 188)
ESTANTE_MARCO = (78, 74, 70)
ENTREPANO = (120, 116, 112)

PIELES = [(172, 190, 214), (138, 158, 188), (96, 118, 150), (74, 92, 122), (52, 64, 88)]
ROPA = [
    (162, 92, 64), (74, 96, 158), (58, 118, 96), (140, 86, 138),
    (52, 62, 84), (176, 148, 92), (96, 104, 116), (128, 60, 72),
]


@dataclass
class Gondola:
    """Un mueble de exhibición con su banda de interacción al frente."""

    zone_id: str
    x1: int
    x2: int
    y_top: int
    y_base: int          # línea del piso donde se apoya el mueble
    profundidad_banda: int  # franja de piso al frente donde se para la gente

    def poligono_banda(self, escena: "EscenaTienda") -> list[list[int]]:
        """
        Zona de análisis: la franja donde cae el CENTROIDE del bbox de una
        persona parada frente a este estante.

        Este detalle es el que hace o rompe todo el análisis. El módulo 1 ubica
        a la persona por el centro de su bounding box, que está a la altura del
        torso, no en los pies. Una zona dibujada sobre el piso frente al mueble
        captura a quien PASA por detrás (su torso queda a esa altura en la
        imagen) y pierde a quien se DETIENE ahí (su torso queda más arriba).
        Es exactamente lo contrario de lo que se busca.

        Se calcula, entonces, dónde estará el torso de alguien parado en la
        banda, y la zona se centra ahí.
        """
        y_pies = self.y_base + self.profundidad_banda // 2
        alto_persona = 150 * escena.escala_en(y_pies)
        centro_y = y_pies - alto_persona / 2

        media_altura = alto_persona * 0.26
        return [
            [self.x1, int(centro_y - media_altura)],
            [self.x2, int(centro_y - media_altura)],
            [self.x2, int(centro_y + media_altura)],
            [self.x1, int(centro_y + media_altura)],
        ]

    @property
    def centro_banda(self) -> tuple[int, int]:
        return (
            (self.x1 + self.x2) // 2,
            self.y_base + self.profundidad_banda // 2,
        )


@dataclass
class Persona:
    """Guion de una persona: qué hace, dónde y cuándo."""

    pid: int
    escenario: str
    gondola: Gondola | None
    frame_entrada: int
    color_ropa: tuple[int, int, int]
    color_piel: tuple[int, int, int]
    altura: float
    velocidad: float
    desde_izquierda: bool
    eventos_esperados: list[dict[str, Any]] = field(default_factory=list)
    trayectoria: list[dict[str, Any]] = field(default_factory=list)


class EscenaTienda:
    """Renderiza la sala: piso en perspectiva, góndolas y fondo."""

    def __init__(self, ancho: int = 960, alto: int = 540, rng: random.Random | None = None):
        self.ancho = ancho
        self.alto = alto
        self.rng = rng or random.Random(0)
        self.horizonte = int(alto * 0.30)

        # Dos hileras de góndolas con un pasillo entre ellas. Las bandas de
        # interacción de la hilera trasera y delantera no se solapan.
        self.gondolas = [
            Gondola("gondola_A1", int(ancho * 0.06), int(ancho * 0.30),
                    self.horizonte + 10, int(alto * 0.56), int(alto * 0.11)),
            Gondola("gondola_A2", int(ancho * 0.34), int(ancho * 0.58),
                    self.horizonte + 10, int(alto * 0.56), int(alto * 0.11)),
            Gondola("gondola_A3", int(ancho * 0.62), int(ancho * 0.94),
                    self.horizonte + 10, int(alto * 0.56), int(alto * 0.11)),
        ]

        self._fondo = self._dibujar_fondo()

    # -- Fondo ------------------------------------------------------------

    def _dibujar_fondo(self) -> np.ndarray:
        img = np.zeros((self.alto, self.ancho, 3), np.uint8)
        img[: self.horizonte] = PARED
        img[self.horizonte:] = PISO

        # Baldosas en perspectiva: dan textura al piso y, sobre todo, hacen que
        # el detector no vea una superficie plana uniforme.
        for i in range(1, 22):
            y = self.horizonte + int((self.alto - self.horizonte) * (i / 22) ** 1.7)
            cv2.line(img, (0, y), (self.ancho, y), (156, 156, 160), 1)
        for i in range(-8, 20):
            x_base = int(self.ancho * (i / 12))
            cv2.line(img, (self.ancho // 2, self.horizonte),
                     (x_base, self.alto), (156, 156, 160), 1)

        for gondola in self.gondolas:
            self._dibujar_gondola(img, gondola)

        # Viñeteado suave: simula caída de iluminación hacia los bordes, que es
        # lo que hace una cámara real de techo.
        yy, xx = np.mgrid[0:self.alto, 0:self.ancho]
        cx, cy = self.ancho / 2, self.alto / 2
        dist = np.sqrt(((xx - cx) / cx) ** 2 + ((yy - cy) / cy) ** 2)
        factor = np.clip(1.0 - 0.22 * dist, 0.6, 1.0)[..., None]
        return np.clip(img * factor, 0, 255).astype(np.uint8)

    def _dibujar_gondola(self, img: np.ndarray, g: Gondola) -> None:
        cv2.rectangle(img, (g.x1, g.y_top), (g.x2, g.y_base), ESTANTE_MARCO, -1)

        n_entrepanos = 5
        alto_util = g.y_base - g.y_top
        for i in range(n_entrepanos):
            y0 = g.y_top + int(alto_util * i / n_entrepanos)
            y1 = g.y_top + int(alto_util * (i + 1) / n_entrepanos) - 4
            cv2.rectangle(img, (g.x1 + 4, y0), (g.x2 - 4, y1), ENTREPANO, -1)

            # Producto: cajas de colores saturados. Es la señal que usa el
            # verificador de escena y la propuesta automática de zonas, así que
            # tiene que estar presente para que el video sintético ejercite esa
            # parte del sistema.
            ancho_prod = max(9, (g.x2 - g.x1) // 16)
            for x in range(g.x1 + 7, g.x2 - ancho_prod, ancho_prod + 3):
                color = tuple(int(v) for v in self.rng.choices(range(40, 250), k=3))
                cv2.rectangle(img, (x, y0 + 3), (x + ancho_prod - 2, y1 - 2), color, -1)
                cv2.rectangle(img, (x, y0 + 3), (x + ancho_prod - 2, y1 - 2), (40, 40, 40), 1)

    def frame_base(self) -> np.ndarray:
        return self._fondo.copy()

    # -- Perspectiva -------------------------------------------------------

    def escala_en(self, y: float) -> float:
        """Escala de una persona según su profundidad: más lejos, más pequeña."""
        t = (y - self.horizonte) / max(1.0, self.alto - self.horizonte)
        return 0.45 + 0.75 * max(0.0, min(1.0, t))

    def zonas_json(self) -> dict[str, Any]:
        return {
            "video_ref": "escena_sintetica",
            "frame_width": self.ancho,
            "frame_height": self.alto,
            "zonas": [
                {"zone_id": g.zone_id, "poligono": g.poligono_banda(self), "es_gondola": True}
                for g in self.gondolas
            ]
            + [
                {
                    "zone_id": "pasillo_central",
                    "poligono": [
                        [0, int(self.alto * 0.72)],
                        [self.ancho, int(self.alto * 0.72)],
                        [self.ancho, self.alto - 1],
                        [0, self.alto - 1],
                    ],
                    "es_gondola": False,
                }
            ],
        }


class RenderPersona:
    """
    Dibuja una figura humana articulada, con brazo extensible hacia el estante.

    La figura es deliberadamente simple pero mantiene las proporciones humanas
    y, sobre todo, la relación ancho/alto del bounding box: esa relación es la
    señal que usa el detector de alcance del módulo 1, así que el video
    sintético solo sirve para validarlo si la reproduce fielmente.
    """

    @staticmethod
    def dibujar(
        img: np.ndarray,
        x: float,
        y_pies: float,
        escala: float,
        color_ropa: tuple[int, int, int],
        color_piel: tuple[int, int, int],
        extension_brazo: float = 0.0,
        hacia_izquierda: bool = False,
        fase_paso: float = 0.0,
    ) -> tuple[int, int, int, int]:
        """Devuelve el bbox real [x1, y1, x2, y2] de lo dibujado."""
        alto = 150 * escala
        ancho_torso = alto * 0.20
        alto_cabeza = alto * 0.13

        x = float(x)
        y_cabeza = y_pies - alto
        y_hombros = y_cabeza + alto_cabeza
        y_cadera = y_pies - alto * 0.46

        # Piernas con oscilación de marcha: sin esto la silueta es un bloque y
        # el bbox no varía como el de una persona caminando.
        sep = ancho_torso * 0.30
        desfase = math.sin(fase_paso) * alto * 0.06
        for signo, d in ((-1, desfase), (1, -desfase)):
            cv2.line(
                img,
                (int(x + signo * sep * 0.5), int(y_cadera)),
                (int(x + signo * sep + d), int(y_pies)),
                color_ropa, max(2, int(7 * escala)), cv2.LINE_AA,
            )

        # Torso
        cv2.rectangle(
            img,
            (int(x - ancho_torso / 2), int(y_hombros)),
            (int(x + ancho_torso / 2), int(y_cadera)),
            color_ropa, -1,
        )

        # Brazos. El del lado del estante se extiende cuando hay alcance.
        largo_brazo = alto * 0.34
        signo_alcance = -1 if hacia_izquierda else 1
        grosor = max(2, int(6 * escala))

        # Brazo pasivo
        cv2.line(
            img,
            (int(x - signo_alcance * ancho_torso / 2), int(y_hombros + alto * 0.03)),
            (int(x - signo_alcance * ancho_torso / 2), int(y_hombros + largo_brazo)),
            color_ropa, grosor, cv2.LINE_AA,
        )

        # Brazo activo: de colgando (0.0) a extendido horizontal (1.0)
        ang = math.radians(90 - 78 * max(0.0, min(1.0, extension_brazo)))
        mx = x + signo_alcance * (ancho_torso / 2 + largo_brazo * math.cos(ang))
        my = y_hombros + alto * 0.03 + largo_brazo * math.sin(ang)
        cv2.line(
            img,
            (int(x + signo_alcance * ancho_torso / 2), int(y_hombros + alto * 0.03)),
            (int(mx), int(my)),
            color_ropa, grosor, cv2.LINE_AA,
        )
        cv2.circle(img, (int(mx), int(my)), max(2, int(4 * escala)), color_piel, -1)

        # Cabeza
        cv2.circle(
            img,
            (int(x), int(y_cabeza + alto_cabeza / 2)),
            int(alto_cabeza / 2), color_piel, -1,
        )

        xs = [x - ancho_torso / 2 - sep, x + ancho_torso / 2 + sep, mx]
        return (
            int(min(xs) - 2), int(y_cabeza - 2),
            int(max(xs) + 2), int(y_pies + 2),
        )


class GeneradorEscena:
    """Arma el guion de cada persona y renderiza el video completo."""

    ESCENARIOS = ["pasa_de_largo", "se_detiene", "toma", "toma_y_devuelve"]
    PESOS = [0.28, 0.20, 0.28, 0.24]

    def __init__(
        self,
        ancho: int = 960,
        alto: int = 540,
        fps: int = 15,
        duracion_s: int = 90,
        n_personas: int = 18,
        seed: int = 7,
    ):
        self.rng = random.Random(seed)
        self.escena = EscenaTienda(ancho, alto, self.rng)
        self.fps = fps
        self.total_frames = fps * duracion_s
        self.n_personas = n_personas
        self.seed = seed

    # -- Guiones -----------------------------------------------------------

    def _crear_personas(self) -> list[Persona]:
        personas = []
        for pid in range(1, self.n_personas + 1):
            escenario = self.rng.choices(self.ESCENARIOS, weights=self.PESOS, k=1)[0]
            gondola = (
                None if escenario == "pasa_de_largo"
                else self.rng.choice(self.escena.gondolas)
            )
            personas.append(
                Persona(
                    pid=pid,
                    escenario=escenario,
                    gondola=gondola,
                    frame_entrada=self.rng.randint(0, max(1, self.total_frames - 200)),
                    color_ropa=self.rng.choice(ROPA),
                    color_piel=self.rng.choice(PIELES),
                    altura=self.rng.uniform(0.92, 1.08),
                    velocidad=self.rng.uniform(1.7, 3.2),
                    desde_izquierda=self.rng.random() < 0.5,
                )
            )
        return personas

    def _guion(self, p: Persona) -> None:
        """
        Construye la trayectoria frame a frame y anota los eventos esperados.

        Cada entrada de `trayectoria` lleva el frame, la posición, la escala y
        la extensión del brazo. El ground truth se anota AQUÍ, en el momento en
        que el guion decide el gesto, no observando el render: así la verdad de
        fondo es exacta por construcción.
        """
        # Los que pasan de largo caminan en primer plano: así su torso queda
        # por debajo de las bandas de interacción y no se cuentan como visitas
        # a una góndola frente a la que nunca estuvieron.
        y_camino = self.escena.alto * self.rng.uniform(0.88, 0.98)
        x_ini = -60 if p.desde_izquierda else self.escena.ancho + 60
        direccion = 1 if p.desde_izquierda else -1

        f = p.frame_entrada
        x = float(x_ini)
        fase = self.rng.uniform(0, 6.28)

        def paso(x_pos: float, brazo: float = 0.0) -> None:
            nonlocal f, fase
            fase += 0.45
            p.trayectoria.append({
                "frame": f,
                "x": x_pos,
                "y": y_camino,
                "brazo": brazo,
                "fase": fase,
            })
            f += 1

        if p.escenario == "pasa_de_largo" or p.gondola is None:
            while -80 < x < self.escena.ancho + 80:
                paso(x)
                x += direccion * p.velocidad
            if p.gondola is not None:
                p.eventos_esperados.append(
                    {"zone_id": p.gondola.zone_id, "event_type": "pass_by"}
                )
            return

        destino_x, y_parada = p.gondola.centro_banda
        y_camino = float(y_parada)

        # Camina hasta quedar frente a la góndola
        while (direccion > 0 and x < destino_x) or (direccion < 0 and x > destino_x):
            paso(x)
            x += direccion * p.velocidad
            if f - p.frame_entrada > self.total_frames:
                return

        # Se detiene: siempre por encima del umbral de 2 s del módulo 5
        quieto = int(self.rng.uniform(3.0, 5.0) * self.fps)
        for _ in range(quieto):
            paso(x)
        p.eventos_esperados.append(
            {"zone_id": p.gondola.zone_id, "event_type": "approach"}
        )

        def alcance() -> None:
            """Extiende el brazo, lo sostiene y lo baja."""
            subida = max(3, int(0.35 * self.fps))
            sostener = max(3, int(0.55 * self.fps))
            for i in range(subida):
                paso(x, brazo=i / subida)
            for _ in range(sostener):
                paso(x, brazo=1.0)
            for i in range(subida):
                paso(x, brazo=1.0 - i / subida)

        if p.escenario in ("toma", "toma_y_devuelve"):
            alcance()
            for _ in range(int(1.4 * self.fps)):
                paso(x)
            p.eventos_esperados.append(
                {"zone_id": p.gondola.zone_id, "event_type": "pickup"}
            )

        if p.escenario == "toma_y_devuelve":
            for _ in range(int(1.6 * self.fps)):
                paso(x)
            alcance()
            for _ in range(int(1.2 * self.fps)):
                paso(x)
            p.eventos_esperados.append(
                {"zone_id": p.gondola.zone_id, "event_type": "return"}
            )
        elif p.escenario == "toma":
            p.eventos_esperados.append(
                {"zone_id": p.gondola.zone_id, "event_type": "takeaway"}
            )

        # Se retira
        while -80 < x < self.escena.ancho + 80:
            paso(x)
            x += direccion * p.velocidad

    # -- Render ------------------------------------------------------------

    def generar(self, ruta_video: Path) -> dict[str, Any]:
        personas = self._crear_personas()
        for p in personas:
            self._guion(p)

        por_frame: dict[int, list[tuple[Persona, dict]]] = {}
        for p in personas:
            for punto in p.trayectoria:
                por_frame.setdefault(punto["frame"], []).append((p, punto))

        ruta_video = Path(ruta_video)
        ruta_video.parent.mkdir(parents=True, exist_ok=True)

        import tempfile

        # isOpened() no basta: con avc1 devuelve True aunque el codificador de
        # H.264 haya fallado al cargar. La única prueba fiable es escribir un
        # frame y comprobar que el archivo tiene contenido.
        codec_elegido = None
        for codec in ("avc1", "H264", "mp4v"):
            with tempfile.TemporaryDirectory() as tmp:
                ruta_prueba = Path(tmp) / "probe.mp4"
                prueba = cv2.VideoWriter(
                    str(ruta_prueba), cv2.VideoWriter_fourcc(*codec),
                    self.fps, (self.escena.ancho, self.escena.alto),
                )
                if prueba.isOpened():
                    prueba.write(
                        np.zeros((self.escena.alto, self.escena.ancho, 3), np.uint8)
                    )
                prueba.release()
                sirve = ruta_prueba.exists() and ruta_prueba.stat().st_size > 1024

            if sirve:
                codec_elegido = codec
                break

        if codec_elegido is None:
            raise RuntimeError("OpenCV no pudo escribir video con ningún códec disponible.")

        print(f"[pipeline] Códec de video: {codec_elegido}")
        if codec_elegido == "mp4v":
            print(
                "[aviso] mp4v no se reproduce en navegadores. Para el tablero, "
                "convierte el archivo o instala la DLL de OpenH264."
            )

        writer = cv2.VideoWriter(
            str(ruta_video), cv2.VideoWriter_fourcc(*codec_elegido),
            self.fps, (self.escena.ancho, self.escena.alto),
        )
        if not writer.isOpened():
            raise RuntimeError(f"No se pudo abrir el escritor de video en {ruta_video}")

        anotaciones: dict[int, list[dict]] = {}

        try:
            for frame_id in range(self.total_frames):
                img = self.escena.frame_base()

                # Dibujar de fondo hacia adelante para que la oclusión sea
                # correcta: quien está más cerca tapa a quien está detrás.
                presentes = sorted(por_frame.get(frame_id, []), key=lambda t: t[1]["y"])

                for persona, punto in presentes:
                    escala = self.escena.escala_en(punto["y"]) * persona.altura
                    hacia_izq = (
                        persona.gondola is not None
                        and punto["x"] > (persona.gondola.x1 + persona.gondola.x2) / 2
                    )
                    bbox = RenderPersona.dibujar(
                        img,
                        punto["x"], punto["y"], escala,
                        persona.color_ropa, persona.color_piel,
                        extension_brazo=punto["brazo"],
                        hacia_izquierda=hacia_izq,
                        fase_paso=punto["fase"],
                    )
                    anotaciones.setdefault(frame_id, []).append(
                        {"person_id": persona.pid, "bbox": list(bbox), "class": "person"}
                    )

                # Ruido de sensor: sin esto la imagen es demasiado limpia y no
                # ejercita la robustez del detector.
                ruido = np.random.normal(0, 3.2, img.shape).astype(np.int16)
                img = np.clip(img.astype(np.int16) + ruido, 0, 255).astype(np.uint8)

                writer.write(img)
                if frame_id % 150 == 0:
                    print(f"[render] frame {frame_id}/{self.total_frames}")
        finally:
            writer.release()

        conteo: dict[str, int] = {}
        for p in personas:
            conteo[p.escenario] = conteo.get(p.escenario, 0) + 1

        ground_truth = {
            "meta": {
                "video": ruta_video.name,
                "fps": self.fps,
                "frames": self.total_frames,
                "resolucion": [self.escena.ancho, self.escena.alto],
                "personas": len(personas),
                "seed": self.seed,
                "escenarios": conteo,
                "naturaleza": (
                    "Escena sintética renderizada. Ninguna persona real fue "
                    "grabada, por lo que no hay dato personal que tratar. La "
                    "verdad de fondo es exacta por construcción: el generador "
                    "decide los eventos, no se anotan observando el video."
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
            json.dumps(ground_truth, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        Path(f"{base}_zonas.json").write_text(
            json.dumps(self.escena.zonas_json(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        # Detecciones perfectas: permiten evaluar la máquina de estados aislada
        # del detector, para saber si un fallo viene de la lógica o de YOLO.
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
        description="Genera video sintético de tienda con ground truth exacto"
    )
    parser.add_argument("--output", default="pipeline/uploads/tienda_sintetica.mp4")
    parser.add_argument("--ancho", type=int, default=960)
    parser.add_argument("--alto", type=int, default=540)
    parser.add_argument("--fps", type=int, default=15)
    parser.add_argument("--duracion", type=int, default=90, help="segundos")
    parser.add_argument("--personas", type=int, default=18)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    generador = GeneradorEscena(
        ancho=args.ancho, alto=args.alto, fps=args.fps,
        duracion_s=args.duracion, n_personas=args.personas, seed=args.seed,
    )
    gt = generador.generar(Path(args.output))
    base = Path(args.output).with_suffix("")

    print(f"[ok] Video: {args.output}")
    print(f"[ok] {gt['meta']['frames']} frames @ {args.fps} fps ({args.duracion} s)")
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
    print(f"[ok] Zonas exactas: {base}_zonas.json")
    print(f"[ok] Detecciones ideales: {base}_detecciones_ideales.jsonl")
    print("\n[!] Ninguna persona real fue grabada: no hay dato personal que tratar.")


if __name__ == "__main__":
    main()
