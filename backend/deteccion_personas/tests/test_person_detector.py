"""
Pruebas basicas del modulo de deteccion de personas.

No dependen de tener un video real: usan una imagen sintetica para
verificar que el pipeline corre sin errores y que la salida respeta
el formato acordado con el equipo (bbox, confidence, class).
"""

import sys
from pathlib import Path
from unittest.mock import Mock

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import person_detector  # noqa: E402
from person_detector import PersonDetector, Detection  # noqa: E402


def test_detection_to_dict_format():
    det = Detection(bbox=[10.234, 20.111, 50.9, 80.4], confidence=0.876543)
    d = det.to_dict()

    assert set(d.keys()) == {"bbox", "confidence", "class"}
    assert d["class"] == "person"
    assert isinstance(d["bbox"], list) and len(d["bbox"]) == 4
    assert d["confidence"] == 0.8765  # redondeado a 4 decimales


def test_detector_runs_on_blank_frame():
    # Frame negro de prueba: no tiene personas, pero el pipeline debe
    # correr sin lanzar excepciones y devolver una lista (vacia o no).
    detector = PersonDetector(conf_threshold=0.4)
    blank_frame = np.zeros((480, 640, 3), dtype=np.uint8)

    detections = detector.detect_frame(blank_frame)

    assert isinstance(detections, list)
    for det in detections:
        assert isinstance(det, Detection)
        assert len(det.bbox) == 4
        assert 0.0 <= det.confidence <= 1.0


def test_synthetic_profile_uses_default_model_if_checkpoint_is_lfs_pointer(
    tmp_path, monkeypatch
):
    checkpoint = tmp_path / "best.pt"
    checkpoint.write_text(
        "version https://git-lfs.github.com/spec/v1\n"
        "oid sha256:placeholder\n"
        "size 123\n",
        encoding="utf-8",
    )
    monkeypatch.setitem(person_detector.PERFILES["sintetico"], "model", str(checkpoint))
    mock_yolo = Mock()
    monkeypatch.setattr(person_detector, "YOLO", mock_yolo)

    with pytest.warns(UserWarning, match="Ultralytics lo descargará"):
        PersonDetector(perfil="sintetico")

    mock_yolo.assert_called_once_with("yolov8n.pt")


if __name__ == "__main__":
    test_detection_to_dict_format()
    test_detector_runs_on_blank_frame()
    print("OK: todas las pruebas pasaron")
