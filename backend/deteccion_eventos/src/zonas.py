"""
zonas.py
Carga de zonas y geometria — Modulo 1 (Deteccion de eventos de interaccion).

Este modulo NO define zonas propias. Lee el archivo del integrante 4
(`mapas_de_calor/config/zonas.json`), que es la fuente unica de verdad del
proyecto.

Tolera los dos esquemas que hoy conviven en el repo:

  A) esquema real usado por los archivos del repo (modulo 4 y modulo 5):
     {"zonas": [{"zone_id": "gondola_A1", "poligono": [[x,y], ...]}]}

  B) esquema documentado en el README del modulo 5:
     {"zones": {"gondola_1": {"name": "...", "vertices": [[x,y], ...]}}}

Se implementa point-in-polygon con ray casting en Python puro (sin OpenCV ni
NumPy) para no agregar dependencias pesadas al modulo y mantener la
viabilidad edge del prototipo.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable


class ZonaError(ValueError):
    """Error de configuracion de zonas."""


class Zona:
    """Una zona del layout (gondola o pasillo)."""

    def __init__(
        self,
        zone_id: str,
        poligono: list[tuple[float, float]],
        nombre: str | None = None,
        es_gondola: bool | None = None,
    ):
        if len(poligono) < 3:
            raise ZonaError(
                f"Zona '{zone_id}' necesita al menos 3 vertices, tiene {len(poligono)}"
            )

        self.zone_id = zone_id
        self.nombre = nombre or zone_id
        self.poligono = poligono

        # Convencion del equipo: los zone_id que empiezan por "gondola" son
        # superficie de exhibicion; el resto (pasillo_*, caja_*) es transito.
        if es_gondola is None:
            es_gondola = zone_id.lower().startswith("gondola")
        self.es_gondola = es_gondola

        xs = [p[0] for p in poligono]
        ys = [p[1] for p in poligono]
        self.bbox = (min(xs), min(ys), max(xs), max(ys))
        self.centroide = (sum(xs) / len(xs), sum(ys) / len(ys))

    def contiene(self, x: float, y: float) -> bool:
        """True si el punto (x, y) cae dentro del poligono (borde incluido)."""
        x1, y1, x2, y2 = self.bbox
        if x < x1 or x > x2 or y < y1 or y > y2:
            return False  # descarte rapido por bounding box

        if self._en_borde(x, y):
            return True

        dentro = False
        n = len(self.poligono)
        for i in range(n):
            ax, ay = self.poligono[i]
            bx, by = self.poligono[(i + 1) % n]
            if (ay > y) != (by > y):
                t = (y - ay) / (by - ay)
                if x < ax + t * (bx - ax):
                    dentro = not dentro
        return dentro

    def _en_borde(self, x: float, y: float, tol: float = 1e-9) -> bool:
        n = len(self.poligono)
        for i in range(n):
            ax, ay = self.poligono[i]
            bx, by = self.poligono[(i + 1) % n]
            cruz = (bx - ax) * (y - ay) - (by - ay) * (x - ax)
            if abs(cruz) > tol:
                continue
            if min(ax, bx) - tol <= x <= max(ax, bx) and (
                min(ay, by) - tol <= y <= max(ay, by)
            ):
                return True
        return False

    def __repr__(self) -> str:  # pragma: no cover - ayuda de depuracion
        return f"Zona({self.zone_id}, gondola={self.es_gondola})"


class Layout:
    """Coleccion de zonas del video de referencia."""

    def __init__(self, zonas: list[Zona], metadata: dict[str, Any] | None = None):
        if not zonas:
            raise ZonaError("El layout no contiene ninguna zona")

        ids = [z.zone_id for z in zonas]
        duplicados = {i for i in ids if ids.count(i) > 1}
        if duplicados:
            raise ZonaError(f"zone_id duplicados en el layout: {sorted(duplicados)}")

        self.zonas = zonas
        self.metadata = metadata or {}
        self._por_id = {z.zone_id: z for z in zonas}

    def __len__(self) -> int:
        return len(self.zonas)

    def __iter__(self) -> Iterable[Zona]:
        return iter(self.zonas)

    def get(self, zone_id: str) -> Zona | None:
        return self._por_id.get(zone_id)

    @property
    def gondolas(self) -> list[Zona]:
        return [z for z in self.zonas if z.es_gondola]

    def zona_de_punto(self, x: float, y: float) -> Zona | None:
        """
        Devuelve la zona que contiene el punto.

        Si el punto cae en varias zonas (poligonos solapados), se prioriza la
        gondola sobre el pasillo: para este modulo interesa la interaccion con
        el estante, no el transito. Este criterio queda documentado porque el
        modulo 5 resuelve el solape tomando simplemente la primera coincidencia
        del diccionario, que depende del orden de lectura del archivo.
        """
        candidatas = [z for z in self.zonas if z.contiene(x, y)]
        if not candidatas:
            return None
        for zona in candidatas:
            if zona.es_gondola:
                return zona
        return candidatas[0]


def _normalizar_puntos(puntos: Any, zone_id: str) -> list[tuple[float, float]]:
    if not isinstance(puntos, (list, tuple)) or not puntos:
        raise ZonaError(f"Zona '{zone_id}' no tiene vertices definidos")

    salida: list[tuple[float, float]] = []
    for punto in puntos:
        if not isinstance(punto, (list, tuple)) or len(punto) != 2:
            raise ZonaError(f"Zona '{zone_id}': cada vertice debe ser [x, y]")
        try:
            salida.append((float(punto[0]), float(punto[1])))
        except (TypeError, ValueError):
            raise ZonaError(
                f"Zona '{zone_id}' tiene vertices no numericos: {punto}"
            ) from None
    return salida


def cargar_layout(ruta: Path | str) -> Layout:
    """
    Carga el layout desde zonas.json (cualquiera de los dos esquemas).

    Raises:
        FileNotFoundError: si el archivo no existe.
        ZonaError: si el contenido no corresponde a ninguno de los esquemas.
    """
    ruta = Path(ruta)
    if not ruta.exists():
        raise FileNotFoundError(f"No existe el archivo de zonas: {ruta}")

    with ruta.open("r", encoding="utf-8") as fh:
        data = json.load(fh)

    if not isinstance(data, dict):
        raise ZonaError(f"{ruta} debe contener un objeto JSON")

    zonas: list[Zona] = []

    if isinstance(data.get("zonas"), list):  # esquema A
        for item in data["zonas"]:
            zone_id = item.get("zone_id")
            if not zone_id:
                raise ZonaError(f"Zona sin 'zone_id' en {ruta}")
            zonas.append(
                Zona(
                    zone_id=zone_id,
                    poligono=_normalizar_puntos(item.get("poligono"), zone_id),
                    nombre=item.get("name"),
                    es_gondola=item.get("es_gondola"),
                )
            )
    elif isinstance(data.get("zones"), dict):  # esquema B
        for zone_id, item in data["zones"].items():
            zonas.append(
                Zona(
                    zone_id=zone_id,
                    poligono=_normalizar_puntos(item.get("vertices"), zone_id),
                    nombre=item.get("name"),
                    es_gondola=item.get("es_gondola"),
                )
            )
    else:
        raise ZonaError(
            f"{ruta} no tiene ni 'zonas' (lista) ni 'zones' (dict); "
            "no corresponde a ningun esquema conocido del proyecto"
        )

    metadata = {
        k: v for k, v in data.items() if k not in ("zonas", "zones")
    }
    metadata.update(data.get("metadata", {}) if isinstance(data.get("metadata"), dict) else {})

    return Layout(zonas, metadata=metadata)


def centroide_bbox(bbox: list[float]) -> tuple[float, float]:
    """
    Centroide = punto medio del bbox — contrato comun del equipo
    (seccion 4.2 de mapas_de_calor/FORMATO_DATOS.md).
    """
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        raise ValueError(f"bbox debe ser [x1, y1, x2, y2], se recibio: {bbox}")
    try:
        x1, y1, x2, y2 = (float(v) for v in bbox)
    except (TypeError, ValueError):
        raise ValueError(f"bbox con coordenadas no numericas: {bbox}") from None
    return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)
