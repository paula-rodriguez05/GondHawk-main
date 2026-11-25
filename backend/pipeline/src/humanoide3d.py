"""
humanoide3d.py
Humanoide 3D articulado — GondHawk.

Figura humana con esqueleto jerárquico: cada extremidad se construye en su
propio sistema de coordenadas y se compone hacia arriba hasta la raíz. Eso
permite animar la marcha y el gesto de alcanzar el estante rotando
articulaciones, no moviendo vértices a mano.

Proporciones
------------
Se usan las proporciones canónicas de figura humana (cabeza ≈ 1/7.5 de la
altura total, envergadura ≈ altura). No es un detalle estético: un detector
entrenado sobre fotografías de personas responde a la proporción antes que al
color o la textura, así que una figura con proporciones correctas se detecta y
una con la cabeza demasiado grande, no.

Jerarquía
---------
    raíz (pelvis)
     ├── torso → cuello → cabeza
     │    ├── hombro.izq → brazo → antebrazo → mano
     │    └── hombro.der → brazo → antebrazo → mano
     ├── cadera.izq → muslo → pantorrilla → pie
     └── cadera.der → muslo → pantorrilla → pie
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from render3d import Malla, caja, cilindro, esfera, matriz_rotacion

# Tonos de piel y ropa en BGR, con rango amplio para que el conjunto de datos
# sintético no quede sesgado a un solo tipo de persona.
PIELES = [
    (176, 194, 218), (150, 172, 202), (122, 146, 180),
    (96, 118, 152), (74, 92, 122), (56, 68, 92),
    (210, 195, 185), (190, 175, 160), (140, 120, 110),
]
CAMISAS = [
    (168, 96, 68), (78, 100, 162), (62, 122, 100), (144, 90, 142),
    (56, 66, 88), (180, 152, 96), (100, 108, 120), (132, 64, 76),
    (208, 206, 200), (48, 52, 60),
    (182, 128, 94), (72, 142, 172), (152, 182, 82),  # más variedad
]
PANTALONES = [
    (72, 64, 58), (52, 56, 74), (40, 42, 48), (96, 88, 78), (64, 72, 88),
    (112, 104, 92), (38, 48, 56),
]
PELOS = [
    (28, 30, 36), (34, 42, 58), (42, 58, 88), (58, 78, 112),
    (86, 112, 148), (48, 48, 52),
]


@dataclass
class Pose:
    """
    Estado articular en un instante.

    Los ángulos van en radianes. `alcance` de 0 a 1 interpola entre el brazo
    colgando y el brazo extendido hacia el frente, que es el gesto que el
    módulo 1 detecta como toma o devolución de producto.
    """

    fase_paso: float = 0.0
    alcance: float = 0.0
    alcance_derecho: bool = True
    giro_cuerpo: float = 0.0     # rotación sobre Y, hacia dónde mira
    inclinacion: float = 0.0     # leve flexión del torso al alcanzar


class Humanoide:
    """Genera las mallas de una persona en una pose dada."""

    def __init__(
        self,
        altura: float = 1.72,
        color_piel: tuple[int, int, int] | None = None,
        color_camisa: tuple[int, int, int] | None = None,
        color_pantalon: tuple[int, int, int] | None = None,
        corpulencia: float = 1.0,
        rng=None,
    ):
        import random

        r = rng or random.Random()
        self.altura = altura
        self.piel = color_piel or r.choice(PIELES)
        self.camisa = color_camisa or r.choice(CAMISAS)
        self.pantalon = color_pantalon or r.choice(PANTALONES)
        self.color_pelo = r.choice(PELOS)
        self.corpulencia = corpulencia

        h = altura
        # Proporciones canónicas escaladas a la altura pedida
        self.alto_cabeza = h * 0.133
        self.alto_cuello = h * 0.035
        self.alto_torso = h * 0.290
        self.ancho_hombros = h * 0.230 * corpulencia
        self.fondo_torso = h * 0.115 * corpulencia
        self.largo_brazo = h * 0.175
        self.largo_antebrazo = h * 0.160
        self.radio_brazo = h * 0.026 * corpulencia
        self.largo_muslo = h * 0.245
        self.largo_pantorrilla = h * 0.235
        self.radio_pierna = h * 0.036 * corpulencia
        self.y_pelvis = self.largo_muslo + self.largo_pantorrilla

    # -- Construcción de la pose ------------------------------------------

    def mallas(self, posicion: np.ndarray, pose: Pose) -> list[Malla]:
        """
        Devuelve las mallas de la figura situada con los pies en `posicion`.

        `posicion` es el punto del piso donde se apoya; el eje Y crece hacia
        arriba, así que la pelvis queda en posicion + y_pelvis.
        """
        giro = matriz_rotacion("y", pose.giro_cuerpo)
        partes: list[Malla] = []

        def agregar(malla: Malla, rot_local: np.ndarray | None, offset_local: np.ndarray):
            """Compone la parte en el espacio del cuerpo y la lleva al mundo."""
            rot = giro @ rot_local if rot_local is not None else giro
            partes.append(malla.transformar(rot, posicion + giro @ offset_local))

        pelvis = np.array([0.0, self.y_pelvis, 0.0])

        # ── Torso ────────────────────────────────────────────────────────
        inclin = matriz_rotacion("x", pose.inclinacion)
        centro_torso = pelvis + inclin @ np.array([0.0, self.alto_torso / 2, 0.0])
        # Torso elíptico: más realista que un cilindro.
        torso = cilindro(
            self.ancho_hombros * 0.30,
            self.alto_torso,
            self.camisa,
            lados=32,
            radio_superior=self.ancho_hombros * 0.36,
            brillo=0.05,
            variacion=0.06,
        )
        torso.vertices[:, 2] *= 0.62   # sección ovalada
        agregar(torso, inclin, centro_torso)

        # Hombros redondeados
        y_hombros = self.alto_torso * 0.42
        for lado in (-1, 1):
            agregar(
                esfera(self.radio_brazo * 1.55, self.camisa, segmentos=24, brillo=0.05, variacion=0.06),
                None,
                pelvis + inclin @ np.array([lado * self.ancho_hombros * 0.43, y_hombros, 0.0]),
            )

        # ── Cuello y cabeza ──────────────────────────────────────────────
        cuello = pelvis + inclin @ np.array([0.0, self.alto_torso + self.alto_cuello / 2, 0.0])
        agregar(
            cilindro(self.radio_brazo * 1.15, self.alto_cuello, self.piel, lados=16, brillo=0.02, variacion=0.04),
            inclin, cuello
        )

        centro_cabeza = pelvis + inclin @ np.array([
            0.0, self.alto_torso + self.alto_cuello + self.alto_cabeza * 0.45, 0.0,
        ])
        cabeza = esfera(
            self.alto_cabeza * 0.46,
            self.piel,
            segmentos=20,
            escala_y=1.18,
            brillo=0.04,
            variacion=0.04,
        )
        agregar(cabeza, inclin, centro_cabeza)

        pelo = esfera(
            self.alto_cabeza * 0.48,
            self.color_pelo,
            segmentos=16,
            escala_y=0.86,
            brillo=0.02,
            variacion=0.06,
        )
        agregar(
            pelo, inclin,
            centro_cabeza + inclin @ np.array([0.0, self.alto_cabeza * 0.10, -self.alto_cabeza * 0.03]),
        )

        # ── Brazos ───────────────────────────────────────────────────────
        for lado in (-1, 1):
            es_activo = (lado == 1) == pose.alcance_derecho
            self._brazo(agregar, pelvis, inclin, lado, pose, es_activo)

        # ── Piernas ──────────────────────────────────────────────────────
        for lado in (-1, 1):
            self._pierna(agregar, pelvis, lado, pose)

        return partes

    def _brazo(self, agregar, pelvis, inclin, lado, pose: Pose, activo: bool) -> None:
        origen = pelvis + inclin @ np.array([
            lado * (self.ancho_hombros * 0.50 + self.radio_brazo),
            self.alto_torso * 0.40,
            -self.fondo_torso * 0.15,
        ])

        if activo and pose.alcance > 0:
            ang_hombro = -math.radians(8 + 82 * pose.alcance)
            ang_codo = -math.radians(30 * (1.0 - pose.alcance) + 4)
        else:
            balanceo = math.sin(pose.fase_paso + (0 if lado > 0 else math.pi))
            ang_hombro = math.radians(20 * balanceo)
            ang_codo = -math.radians(16 + 10 * abs(balanceo))

        rot_hombro = inclin @ matriz_rotacion("x", ang_hombro)
        centro_brazo = origen + rot_hombro @ np.array([0.0, -self.largo_brazo / 2, 0.0])
        agregar(
            cilindro(
                self.radio_brazo,
                self.largo_brazo,
                self.camisa,
                lados=20,
                radio_superior=self.radio_brazo * 1.12,
                brillo=0.03,
                variacion=0.05,
            ),
            rot_hombro, centro_brazo,
        )

        codo = origen + rot_hombro @ np.array([0.0, -self.largo_brazo, 0.0])
        rot_codo = rot_hombro @ matriz_rotacion("x", ang_codo)
        centro_ante = codo + rot_codo @ np.array([0.0, -self.largo_antebrazo / 2, 0.0])
        agregar(
            cilindro(
                self.radio_brazo * 0.72,
                self.largo_antebrazo,
                self.piel,
                lados=20,
                radio_superior=self.radio_brazo * 0.90,
                brillo=0.02,
                variacion=0.05,
            ),
            rot_codo, centro_ante,
        )

        mano = codo + rot_codo @ np.array([0.0, -self.largo_antebrazo, 0.0])
        agregar(
            esfera(self.radio_brazo * 0.95, self.piel, segmentos=14, escala_y=1.25, brillo=0.02, variacion=0.04),
            None, mano
        )

    def _pierna(self, agregar, pelvis, lado, pose: Pose) -> None:
        origen = pelvis + np.array([lado * self.ancho_hombros * 0.22, 0.0, 0.0])

        balanceo = math.sin(pose.fase_paso + (math.pi if lado > 0 else 0))
        ang_cadera = math.radians(24 * balanceo)
        ang_rodilla = -math.radians(10 + 34 * max(0.0, -balanceo))

        rot_cadera = matriz_rotacion("x", ang_cadera)
        centro_muslo = origen + rot_cadera @ np.array([0.0, -self.largo_muslo / 2, 0.0])
        agregar(
            cilindro(
                self.radio_pierna * 0.86,
                self.largo_muslo,
                self.pantalon,
                lados=20,
                radio_superior=self.radio_pierna * 1.08,
                brillo=0.03,
                variacion=0.06,
            ),
            rot_cadera, centro_muslo,
        )

        rodilla = origen + rot_cadera @ np.array([0.0, -self.largo_muslo, 0.0])
        rot_rodilla = rot_cadera @ matriz_rotacion("x", ang_rodilla)
        centro_pant = rodilla + rot_rodilla @ np.array([0.0, -self.largo_pantorrilla / 2, 0.0])
        agregar(
            cilindro(
                self.radio_pierna * 0.62,
                self.largo_pantorrilla,
                self.pantalon,
                lados=20,
                radio_superior=self.radio_pierna * 0.88,
                brillo=0.02,
                variacion=0.06,
            ),
            rot_rodilla, centro_pant,
        )

        tobillo = rodilla + rot_rodilla @ np.array([0.0, -self.largo_pantorrilla, 0.0])
        pie = caja(
            self.radio_pierna * 2.0,
            self.radio_pierna * 1.1,
            self.altura * 0.085,
            (34, 34, 38),
            brillo=0.01,
            variacion=0.08,
        )
        agregar(
            pie,
            rot_rodilla,
            tobillo + np.array([0.0, self.radio_pierna * 0.5, self.altura * 0.022]),
        )

    # -- Utilidad ---------------------------------------------------------

    def malla_unida(self, posicion: np.ndarray, pose: Pose) -> Malla:
        """
        Une todas las partes en una sola malla.

        Sirve para calcular el bounding box exacto de la persona completa en
        una sola proyección, que es el ground truth que consume el evaluador.
        """
        partes = self.mallas(posicion, pose)
        vertices, caras, offset = [], [], 0
        for p in partes:
            vertices.append(p.vertices)
            caras.append(p.caras + offset)
            offset += len(p.vertices)
        return Malla(
            np.concatenate(vertices), np.concatenate(caras), self.camisa,
        )