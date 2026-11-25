"""
render3d.py
Motor de render 3D — GondHawk.

Renderizador por software escrito sobre NumPy y OpenCV. No es un motor de
juego: es lo mínimo necesario para generar escenas de tienda con humanoides
articulados, geometría real en tres dimensiones y sombreado, sin depender de
Blender, Unity ni de una GPU.

Qué implementa
--------------
- Álgebra 3D: transformaciones, rotaciones y matriz de cámara look-at.
- Proyección en perspectiva con distancia focal y plano de recorte.
- Mallas triangulares: cajas y cilindros, con normales por cara.
- Algoritmo del pintor con orden por profundidad y recorte del plano cercano.
- Sombreado Lambertiano con luz direccional, luz ambiental y término
  especular suave.
- Sombras proyectadas sobre el plano del piso.
- Variación de color por cara para simular textura.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import cv2
import numpy as np

# ── Álgebra ─────────────────────────────────────────────────────────────────


def normalizar(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    return v / n if n > 1e-9 else v


def normalizar_filas(m: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(m, axis=1, keepdims=True)
    return m / np.maximum(n, 1e-9)


def matriz_rotacion(eje: str, angulo: float) -> np.ndarray:
    c, s = math.cos(angulo), math.sin(angulo)
    if eje == "x":
        return np.array([[1, 0, 0], [0, c, -s], [0, s, c]], dtype=np.float64)
    if eje == "y":
        return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]], dtype=np.float64)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]], dtype=np.float64)


@dataclass
class Camara:
    """
    Cámara en perspectiva definida por posición y punto de mira.

    El sistema de coordenadas del mundo es Y arriba, con el piso en Y=0.
    Los valores por defecto imitan una cámara de seguridad de techo: elevada,
    inclinada hacia abajo y con lente moderadamente angular.
    """

    posicion: np.ndarray = field(
        default_factory=lambda: np.array([0.0, 3.2, -6.5])
    )
    objetivo: np.ndarray = field(
        default_factory=lambda: np.array([0.0, 1.0, 2.0])
    )
    fov_grados: float = 58.0
    ancho: int = 960
    alto: int = 540
    cerca: float = 0.25

    def __post_init__(self) -> None:
        self._actualizar()

    def _actualizar(self) -> None:
        adelante = normalizar(self.objetivo - self.posicion)
        derecha = normalizar(np.cross(adelante, np.array([0.0, 1.0, 0.0])))
        arriba = np.cross(derecha, adelante)
        self.vista = np.stack([derecha, arriba, adelante])
        self.focal = (self.ancho / 2) / math.tan(math.radians(self.fov_grados) / 2)

    def a_camara(self, puntos: np.ndarray) -> np.ndarray:
        return (puntos - self.posicion) @ self.vista.T

    def proyectar(self, puntos_camara: np.ndarray) -> np.ndarray:
        z = np.maximum(puntos_camara[:, 2], self.cerca)
        x = self.ancho / 2 + self.focal * puntos_camara[:, 0] / z
        y = self.alto / 2 - self.focal * puntos_camara[:, 1] / z
        return np.stack([x, y], axis=1)


# ── Mallas ──────────────────────────────────────────────────────────────────


@dataclass
class Malla:
    """Malla triangular con color por material."""

    vertices: np.ndarray           # (N, 3)
    caras: np.ndarray              # (M, 3) índices
    color: tuple[int, int, int]
    brillo: float = 0.0            # 0 = mate, 1 = muy especular
    suave: bool = False            # sombreado interpolado en vez de facetado
    variacion: float = 0.0         # ruido de color por cara, simula textura

    def transformar(self, rotacion: np.ndarray | None, traslacion: np.ndarray) -> "Malla":
        v = self.vertices @ rotacion.T if rotacion is not None else self.vertices
        return Malla(
            v + traslacion, self.caras, self.color, self.brillo,
            self.suave, self.variacion,
        )


def caja(ancho: float, alto: float, fondo: float, color, brillo: float = 0.0, variacion: float = 0.0) -> Malla:
    x, y, z = ancho / 2, alto / 2, fondo / 2
    v = np.array([
        [-x, -y, -z], [x, -y, -z], [x, y, -z], [-x, y, -z],
        [-x, -y, z], [x, -y, z], [x, y, z], [-x, y, z],
    ], dtype=np.float64)
    c = np.array([
        [0, 1, 2], [0, 2, 3],
        [5, 4, 7], [5, 7, 6],
        [4, 0, 3], [4, 3, 7],
        [1, 5, 6], [1, 6, 2],
        [3, 2, 6], [3, 6, 7],
        [4, 5, 1], [4, 1, 0],
    ], dtype=np.int32)
    return Malla(v, c, color, brillo, suave=False, variacion=variacion)


def cilindro(
    radio: float, alto: float, color, lados: int = 20,
    brillo: float = 0.0, radio_superior: float | None = None,
    variacion: float = 0.0,
) -> Malla:
    r_sup = radio if radio_superior is None else radio_superior

    angulos = np.linspace(0, 2 * math.pi, lados, endpoint=False)
    circulo = np.stack([np.cos(angulos) * radio, np.sin(angulos) * radio], axis=1)
    circulo_sup = np.stack([np.cos(angulos) * r_sup, np.sin(angulos) * r_sup], axis=1)

    abajo = np.concatenate([circulo[:, :1], np.full((lados, 1), -alto / 2), circulo[:, 1:]], axis=1)
    arriba = np.concatenate(
        [circulo_sup[:, :1], np.full((lados, 1), alto / 2), circulo_sup[:, 1:]], axis=1)
    v = np.concatenate([abajo, arriba], axis=0)

    caras = []
    for i in range(lados):
        j = (i + 1) % lados
        caras.append([i, j, lados + j])
        caras.append([i, lados + j, lados + i])
    for i in range(1, lados - 1):
        caras.append([0, i, i + 1])
        caras.append([lados, lados + i + 1, lados + i])

    return Malla(v, np.array(caras, dtype=np.int32), color, brillo, suave=True, variacion=variacion)


def esfera(radio: float, color, segmentos: int = 18, brillo: float = 0.0,
           escala_y: float = 1.0, variacion: float = 0.0) -> Malla:
    vs, caras = [], []
    for i in range(segmentos + 1):
        phi = math.pi * i / segmentos
        for j in range(segmentos):
            theta = 2 * math.pi * j / segmentos
            vs.append([
                radio * math.sin(phi) * math.cos(theta),
                radio * math.cos(phi) * escala_y,
                radio * math.sin(phi) * math.sin(theta),
            ])
    for i in range(segmentos):
        for j in range(segmentos):
            a = i * segmentos + j
            b = i * segmentos + (j + 1) % segmentos
            c = (i + 1) * segmentos + j
            d = (i + 1) * segmentos + (j + 1) % segmentos
            caras.append([a, b, d])
            caras.append([a, d, c])
    return Malla(
        np.array(vs, dtype=np.float64), np.array(caras, dtype=np.int32),
        color, brillo, suave=True, variacion=variacion,
    )


# ── Render ──────────────────────────────────────────────────────────────────


class Renderer:
    """
    Rasterizador por software con algoritmo del pintor.

    Se ordenan las caras por profundidad y se pintan de atrás hacia adelante.
    Es O(n log n) y para escenas de este tamaño (unas 3.000 caras) rinde de
    sobra. Un z-buffer por píxel daría intersecciones correctas, pero aquí no
    hay geometría que se atraviese a sí misma.
    """

    def __init__(
        self,
        camara: Camara,
        luz: np.ndarray | None = None,
        ambiental: float = 0.55,
        color_cielo: tuple[int, int, int] = (188, 182, 172),
        post_proceso: bool = True,
    ):
        self.camara = camara
        # Luz más lateral para resaltar volúmenes
        self.luz = normalizar(luz if luz is not None else np.array([-0.3, -0.8, 0.5]))
        self.ambiental = ambiental
        self.color_cielo = color_cielo
        self.post_proceso = post_proceso

    def render(
        self,
        mallas: list[Malla],
        sombras: bool = True,
        altura_piso: float = 0.0,
    ) -> np.ndarray:
        img = np.full((self.camara.alto, self.camara.ancho, 3), self.color_cielo, np.uint8)

        caras: list[tuple[float, np.ndarray, tuple[int, int, int]]] = []

        for malla in mallas:
            if sombras and malla.color != (0, 0, 0):
                caras.extend(self._caras_de_sombra(malla, altura_piso))
            caras.extend(self._caras_iluminadas(malla))

        caras.sort(key=lambda c: -c[0])

        for _, poligono, color in caras:
            cv2.fillConvexPoly(img, poligono, color, lineType=cv2.LINE_AA)

        return self._post_proceso(img)

    def _post_proceso(self, img: np.ndarray) -> np.ndarray:
        if not self.post_proceso:
            return img

        # Desenfoque más suave
        img = cv2.GaussianBlur(img, (3, 3), 0.6)

        # Textura de superficie con más intensidad
        h, w = img.shape[:2]
        textura = np.random.normal(0, 3.0, (h // 6, w // 6, 3))
        textura = cv2.resize(textura, (w, h), interpolation=cv2.INTER_CUBIC)

        gris = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
        escala = (1.6 - 0.8 * gris)[..., None]
        grano = np.random.normal(0, 2.0, img.shape) * escala

        img = np.clip(img.astype(np.float32) + textura + grano, 0, 255).astype(np.uint8)

        # Pequeño ajuste de contraste y saturación (simula procesamiento de cámara)
        img = cv2.convertScaleAbs(img, alpha=1.05, beta=2)

        return img

    def _caras_iluminadas(self, malla: Malla):
        cam = self.camara
        v_cam = cam.a_camara(malla.vertices)
        tri_mundo = malla.vertices[malla.caras]
        tri_cam = v_cam[malla.caras]

        visibles = (tri_cam[:, :, 2] > cam.cerca).all(axis=1)
        if not visibles.any():
            return []

        tri_mundo = tri_mundo[visibles]
        tri_cam = tri_cam[visibles]

        bordes1 = tri_cam[:, 1] - tri_cam[:, 0]
        bordes2 = tri_cam[:, 2] - tri_cam[:, 0]
        normales_cam = np.cross(bordes1, bordes2)
        mirando = (normales_cam * tri_cam[:, 0]).sum(axis=1) < 0
        if not mirando.any():
            return []

        tri_mundo = tri_mundo[mirando]
        tri_cam = tri_cam[mirando]

        n_mundo = np.cross(
            tri_mundo[:, 1] - tri_mundo[:, 0],
            tri_mundo[:, 2] - tri_mundo[:, 0],
        )
        norma = np.linalg.norm(n_mundo, axis=1, keepdims=True)
        n_mundo = n_mundo / np.maximum(norma, 1e-9)

        difusa = np.clip((-n_mundo @ self.luz), 0.0, 1.0)
        intensidad = self.ambiental + (1.0 - self.ambiental) * difusa

        if malla.brillo > 0:
            vista = normalizar(np.array([0.0, 0.0, -1.0]))
            reflejo = self.luz - 2 * (n_mundo @ self.luz)[:, None] * n_mundo
            spec = np.clip((reflejo @ -vista), 0.0, 1.0) ** 20  # más brillante
            intensidad = intensidad + malla.brillo * spec

        if malla.suave:
            centro = malla.vertices.mean(axis=0)
            radial = tri_mundo.mean(axis=1) - centro
            norma_r = np.linalg.norm(radial, axis=1, keepdims=True)
            radial = radial / np.maximum(norma_r, 1e-9)
            n_suave = normalizar_filas(0.4 * n_mundo + 0.6 * radial)  # más suave
            difusa_suave = np.clip((-n_suave @ self.luz), 0.0, 1.0)
            intensidad = self.ambiental + (1.0 - self.ambiental) * difusa_suave

        # Aplicar variación de color por cara
        base = np.array(malla.color, dtype=np.float64)
        if malla.variacion > 0:
            # Generar ruido por cara: sumamos/restamos hasta variacion*255
            ruido = (np.random.rand(len(tri_mundo), 3) - 0.5) * 2 * malla.variacion * 255
            colores = base[None, :] * intensidad[:, None] + ruido
        else:
            colores = base[None, :] * intensidad[:, None]

        colores = np.clip(colores, 0, 255).astype(np.uint8)

        pts = cam.proyectar(tri_cam.reshape(-1, 3)).reshape(-1, 3, 2)
        prof = tri_cam[:, :, 2].mean(axis=1)

        salida = []
        for i in range(len(pts)):
            salida.append((
                float(prof[i]),
                pts[i].astype(np.int32),
                tuple(int(c) for c in colores[i]),
            ))
        return salida

    def _caras_de_sombra(self, malla: Malla, altura_piso: float):
        if abs(self.luz[1]) < 1e-6:
            return []

        v = malla.vertices
        t = (altura_piso - v[:, 1]) / self.luz[1]
        proyectados = v + t[:, None] * self.luz[None, :]
        proyectados[:, 1] = altura_piso + 0.002

        cam = self.camara
        v_cam = cam.a_camara(proyectados)
        tri_cam = v_cam[malla.caras]

        visibles = (tri_cam[:, :, 2] > cam.cerca).all(axis=1)
        if not visibles.any():
            return []
        tri_cam = tri_cam[visibles]

        pts = cam.proyectar(tri_cam.reshape(-1, 3)).reshape(-1, 3, 2)
        prof = tri_cam[:, :, 2].mean(axis=1)

        return [
            (float(prof[i]) + 0.01, pts[i].astype(np.int32), (96, 94, 92))
            for i in range(len(pts))
        ]

    def bbox_de(self, malla: Malla) -> tuple[int, int, int, int] | None:
        cam = self.camara
        v_cam = cam.a_camara(malla.vertices)
        delante = v_cam[:, 2] > cam.cerca
        if not delante.any():
            return None

        pts = cam.proyectar(v_cam[delante])
        x1, y1 = pts.min(axis=0)
        x2, y2 = pts.max(axis=0)

        if x2 < 0 or y2 < 0 or x1 > cam.ancho or y1 > cam.alto:
            return None

        return (
            int(max(0, x1)), int(max(0, y1)),
            int(min(cam.ancho - 1, x2)), int(min(cam.alto - 1, y2)),
        )