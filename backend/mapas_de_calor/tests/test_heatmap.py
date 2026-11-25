"""
Tests del modulo de heatmap y zonas, con datos 100% sinteticos
(sin necesitar vtest.avi ni correr la deteccion/tracking reales).

Cubre:
  - point_in_polygon (referencia geometrica)
  - build_heatmap_and_counts con el formato REAL de Juan (person_id entero)
  - fallback bbox -> centroide
  - normalizacion person_id -> track_id string (compatible con Paula)
  - compatibilidad con el formato alternativo track_id
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from heatmap_generator import build_heatmap_and_counts, point_in_polygon  # noqa: E402
from trajectory_reader import read_trajectories  # noqa: E402

# Regex del validador de privacidad del modulo 8 (Paula)
REGEX_PAULA = re.compile(r"^[0-9a-fA-F]{1,8}(-[0-9a-fA-F]{1,12}){0,4}$")


def _write_jsonl(path, records):
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


ZONAS_TEST = {
    "video_ref": "test.avi",
    "frame_width": 100,
    "frame_height": 100,
    "zonas": [
        {"zone_id": "zona_A", "poligono": [[0, 0], [10, 0], [10, 10], [0, 10]]},
        {"zone_id": "zona_B", "poligono": [[40, 40], [60, 40], [60, 60], [40, 60]]},
    ],
}


def test_point_in_polygon_basico():
    cuadrado = [[0, 0], [10, 0], [10, 10], [0, 10]]
    assert point_in_polygon((5, 5), cuadrado) is True
    assert point_in_polygon((15, 5), cuadrado) is False


def test_formato_real_de_juan(tmp_path):
    """El formato que emite el tracker real de Juan: person_id ENTERO y solo bbox
    (sin centroid). Debe leerse, derivarse el centroide y contar las zonas."""
    trayectorias_path = tmp_path / "tracking.jsonl"
    registros = [
        {"frame_id": 0, "timestamp_ms": 0.0, "tracks": [
            {"person_id": 1, "bbox": [0, 0, 10, 10], "class": "person"},
        ]},
        {"frame_id": 1, "timestamp_ms": 100.0, "tracks": [
            {"person_id": 1, "bbox": [1, 1, 11, 11], "class": "person"},
            {"person_id": 2, "bbox": [45, 45, 55, 55], "class": "person"},
        ]},
    ]
    _write_jsonl(trayectorias_path, registros)

    heatmap, conteos = build_heatmap_and_counts(str(trayectorias_path), ZONAS_TEST)

    assert heatmap.shape == (100, 100)
    assert heatmap[5, 5] == 1  # frame 0: persona 1 con centroide (5,5)
    assert heatmap[6, 6] == 1  # frame 1: persona 1 se movio a centroide (6,6)
    assert heatmap[50, 50] == 1  # persona 2 en zona_B
    conteo_por_id = {z["zone_id"]: z for z in conteos["zonas"]}
    assert conteo_por_id["zona_A"]["visitas_unicas"] == 1  # solo person_id 1
    assert conteo_por_id["zona_B"]["visitas_unicas"] == 1  # solo person_id 2
    assert conteos["frames_procesados"] == 2


def test_person_id_se_normaliza_a_track_id_compatible_con_paula(tmp_path):
    """str(person_id) debe pasar el regex del validador del modulo 8."""
    trayectorias_path = tmp_path / "tracking.jsonl"
    registros = [
        {"frame_id": 0, "timestamp_ms": 0.0, "tracks": [
            {"person_id": 31, "bbox": [0, 0, 10, 10], "class": "person"},
        ]},
    ]
    _write_jsonl(trayectorias_path, registros)

    puntos = list(read_trajectories(str(trayectorias_path)))
    assert len(puntos) == 1
    assert puntos[0].track_id == "31"
    assert REGEX_PAULA.match(puntos[0].track_id), \
        "str(person_id) debe cumplir el regex del validador de Paula"


def test_compatibilidad_formato_track_id(tmp_path):
    """Si el tracker usara track_id (p. ej. datos simulados antiguos), tambien funciona."""
    trayectorias_path = tmp_path / "tracking_alt.jsonl"
    registros = [
        {"frame_id": 0, "timestamp_ms": 0.0, "tracks": [
            {"track_id": "a3f19c2b", "bbox": [0, 0, 10, 10]},
        ]},
    ]
    _write_jsonl(trayectorias_path, registros)

    puntos = list(read_trajectories(str(trayectorias_path)))
    assert puntos[0].track_id == "a3f19c2b"
    assert puntos[0].centroid == (5.0, 5.0)  # derivado del bbox


def test_bbox_fallback_a_centroide(tmp_path):
    """Sin centroid, el centroide se deriva del bbox (punto medio)."""
    trayectorias_path = tmp_path / "t.jsonl"
    registros = [
        {"frame_id": 0, "timestamp_ms": 0.0, "tracks": [
            {"person_id": 7, "bbox": [10, 20, 30, 60], "class": "person"},
        ]},
    ]
    _write_jsonl(trayectorias_path, registros)

    puntos = list(read_trajectories(str(trayectorias_path)))
    assert puntos[0].centroid == (20.0, 40.0)


if __name__ == "__main__":
    print("Ejecuta con: pytest tests/ -v")
