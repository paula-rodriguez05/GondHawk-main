"""
test_pipeline.py
Tests del módulo 6 — Backend / Pipeline (Laura) — GondHawk.

Verifica que el pipeline:
  1. Importa correctamente todos los módulos del proyecto.
  2. Genera todos los archivos de salida esperados.
  3. Los archivos JSONL tienen el formato correcto.
  4. Las métricas finales son coherentes (no negativos, tasas entre 0 y 1).
  5. No guarda ningún dato que pueda identificar personas (privacidad).

Ejecución:
    python -m pytest pipeline/tests/test_pipeline.py -v
    # o desde la raíz:
    pytest pipeline/tests/test_pipeline.py -v
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

# Añadimos los src de todos los módulos al path
# NOTA (Laura): este archivo vive en <repo>/pipeline/tests/test_pipeline.py,
# igual de "profundo" que pipeline/src/pipeline.py. parents[2] es la raíz del
# repo (parents[0]=pipeline/tests, parents[1]=pipeline, parents[2]=<repo>).
# Antes decía parents[3], que apunta un nivel POR ENCIMA de la raíz del repo
# → sys.path apuntaba a carpetas que no existen → ModuleNotFoundError en
# todos los imports de este archivo.
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "deteccion_personas" / "src"))
sys.path.insert(0, str(ROOT / "tracking" / "src"))
sys.path.insert(0, str(ROOT / "mapas_de_calor" / "src"))
sys.path.insert(0, str(ROOT / "tiempo_permanencia" / "src"))
sys.path.insert(0, str(ROOT / "deteccion_eventos" / "src"))
sys.path.insert(0, str(ROOT / "pipeline" / "src"))

# NOTA (Laura): mapas_de_calor/src/trajectory_reader.py (Arturo) y
# tiempo_permanencia/src/trajectory_reader.py (Diego) tienen el mismo nombre
# de archivo. pipeline.py ya sabe resolver esa colisión (ver comentario en
# pipeline/src/pipeline.py), pero SOLO cuando es él quien importa
# heatmap_generator y dwell_time primero. Si un test de este archivo importa
# heatmap_generator o dwell_time directamente ANTES de que pipeline.py haya
# corrido su propia lógica, vuelve a chocar. Por eso importamos "pipeline" una
# sola vez aquí, a nivel de módulo — apenas se recolecta este archivo de
# tests, antes de que corra cualquier test individual — para que
# heatmap_generator y dwell_time queden bien cacheados en sys.modules sin
# importar en qué orden pytest decida ejecutar los tests después.
from pipeline import GondolaPipeline as _GondolaPipeline  # noqa: F401 (precarga intencional)


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def zonas_path() -> Path:
    """Ruta al zonas.json oficial del proyecto (fuente única)."""
    p = ROOT / "mapas_de_calor" / "config" / "zonas.json"
    if not p.exists():
        pytest.skip("zonas.json no disponible — ejecutar primero el módulo 4")
    return p


@pytest.fixture
def outdir(tmp_path) -> Path:
    """Carpeta temporal para los archivos de salida del test."""
    return tmp_path / "pipeline_output"


@pytest.fixture
def video_sintetico(tmp_path) -> Path:
    """
    Genera un video sintético mínimo (10 frames, 320×240, 25fps) para
    ejecutar el pipeline sin necesitar un video real.
    """
    try:
        import cv2
    except ImportError:
        pytest.skip("opencv-python no instalado")

    path = tmp_path / "test_video.avi"
    fourcc = cv2.VideoWriter_fourcc(*"MJPG")
    writer = cv2.VideoWriter(str(path), fourcc, 25.0, (320, 240))
    for i in range(10):
        # Frame gris con un rectángulo blanco (simula una "persona")
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        x = 50 + i * 5
        cv2.rectangle(frame, (x, 80), (x + 40, 180), (200, 200, 200), -1)
        writer.write(frame)
    writer.release()
    return path


# ── Tests de importación ──────────────────────────────────────────────────────

class TestImportaciones:
    """Verifica que todos los módulos se pueden importar desde el pipeline."""

    def test_importar_person_detector(self):
        from person_detector import PersonDetector
        assert PersonDetector is not None

    def test_importar_tracker(self):
        from tracker import PersonTracker
        assert PersonTracker is not None

    def test_importar_heatmap_generator(self):
        from heatmap_generator import smooth_heatmap, render_heatmap_image
        assert smooth_heatmap is not None

    def test_importar_dwell_time(self):
        from dwell_time import DwellTimeAnalyzer
        assert DwellTimeAnalyzer is not None

    def test_importar_state_machine(self):
        from state_machine import InteractionStateMachine
        assert InteractionStateMachine is not None

    def test_importar_pipeline(self):
        from pipeline import GondolaPipeline
        assert GondolaPipeline is not None


# ── Tests del pipeline con video sintético ────────────────────────────────────

class TestPipelineIntegracion:
    """Pruebas de integración usando el video sintético."""

    def test_pipeline_genera_archivos_de_salida(
        self, video_sintetico, zonas_path, outdir
    ):
        """El pipeline debe generar todos los archivos esperados."""
        from pipeline import GondolaPipeline

        p = GondolaPipeline(
            video_source=str(video_sintetico),
            zonas_path=zonas_path,
            outdir=outdir,
            max_frames=10,
        )
        resumen = p.run()

        archivos_esperados = [
            "detecciones.jsonl",
            "detecciones.meta.json",
            "tracking.jsonl",
            "dwell_time.jsonl",
            "eventos_interaccion.jsonl",
            "eventos_compliance.jsonl",
            "metricas_interaccion.json",
            "metricas_pipeline.json",
            "conteo_zonas.json",
        ]
        for nombre in archivos_esperados:
            assert (outdir / nombre).exists(), f"Falta el archivo: {nombre}"

    def test_detecciones_jsonl_formato(self, video_sintetico, zonas_path, outdir):
        """Cada línea de detecciones.jsonl debe tener frame_id, timestamp_ms y detections."""
        from pipeline import GondolaPipeline

        GondolaPipeline(
            video_source=str(video_sintetico),
            zonas_path=zonas_path,
            outdir=outdir,
            max_frames=10,
        ).run()

        with open(outdir / "detecciones.jsonl", encoding="utf-8") as fh:
            for linea in fh:
                registro = json.loads(linea)
                assert "frame_id" in registro
                assert "timestamp_ms" in registro
                assert "detections" in registro
                assert isinstance(registro["detections"], list)

    def test_tracking_jsonl_formato(self, video_sintetico, zonas_path, outdir):
        """Cada línea de tracking.jsonl debe tener frame_id, timestamp_ms y tracks."""
        from pipeline import GondolaPipeline

        GondolaPipeline(
            video_source=str(video_sintetico),
            zonas_path=zonas_path,
            outdir=outdir,
            max_frames=10,
        ).run()

        with open(outdir / "tracking.jsonl", encoding="utf-8") as fh:
            for linea in fh:
                registro = json.loads(linea)
                assert "frame_id" in registro
                assert "timestamp_ms" in registro
                assert "tracks" in registro
                assert isinstance(registro["tracks"], list)

    def test_metricas_pipeline_coherencia(self, video_sintetico, zonas_path, outdir):
        """Las métricas globales no deben tener valores negativos ni tasas > 1."""
        from pipeline import GondolaPipeline

        resumen = GondolaPipeline(
            video_source=str(video_sintetico),
            zonas_path=zonas_path,
            outdir=outdir,
            max_frames=10,
        ).run()

        embudo = resumen["embudo_global"]
        assert embudo["visitas"] >= 0
        assert embudo["se_detiene"] >= 0
        assert embudo["toma_producto"] >= 0
        assert embudo["devuelve"] >= 0
        assert 0.0 <= embudo["tasa_interaccion"] <= 1.0
        assert 0.0 <= embudo["tasa_rechazo"] <= 1.0

    def test_frames_procesados_correctos(self, video_sintetico, zonas_path, outdir):
        """El número de frames procesados debe coincidir con max_frames."""
        from pipeline import GondolaPipeline

        resumen = GondolaPipeline(
            video_source=str(video_sintetico),
            zonas_path=zonas_path,
            outdir=outdir,
            max_frames=5,
        ).run()

        assert resumen["frames_procesados"] == 5

    def test_meta_json_tiene_resolucion(self, video_sintetico, zonas_path, outdir):
        """detecciones.meta.json debe tener frame_width y frame_height."""
        from pipeline import GondolaPipeline

        GondolaPipeline(
            video_source=str(video_sintetico),
            zonas_path=zonas_path,
            outdir=outdir,
            max_frames=5,
        ).run()

        meta = json.loads((outdir / "detecciones.meta.json").read_text(encoding="utf-8"))
        assert "frame_width" in meta
        assert "frame_height" in meta
        assert meta["frame_width"] == 320
        assert meta["frame_height"] == 240


# ── Tests de privacidad ───────────────────────────────────────────────────────

class TestPrivacidad:
    """
    Verifica que ningún archivo de salida contiene datos que puedan
    identificar a una persona (Ley 1581 de 2012).
    """

    CAMPOS_PROHIBIDOS = [
        "face",
        "cara",
        "rostro",
        "biometric",
        "nombre",
        "name",
        "dni",
        "cedula",
        "email",
        "telefono",
    ]

    def _leer_jsonl(self, path: Path) -> list[dict]:
        registros = []
        with open(path, encoding="utf-8") as fh:
            for linea in fh:
                if linea.strip():
                    registros.append(json.loads(linea))
        return registros

    def test_detecciones_no_tiene_datos_personales(
        self, video_sintetico, zonas_path, outdir
    ):
        from pipeline import GondolaPipeline

        GondolaPipeline(
            video_source=str(video_sintetico),
            zonas_path=zonas_path,
            outdir=outdir,
            max_frames=5,
        ).run()

        registros = self._leer_jsonl(outdir / "detecciones.jsonl")
        for registro in registros:
            texto = json.dumps(registro).lower()
            for campo in self.CAMPOS_PROHIBIDOS:
                assert campo not in texto, (
                    f"Campo prohibido '{campo}' encontrado en detecciones.jsonl"
                )

    def test_eventos_compliance_solo_campos_permitidos(
        self, video_sintetico, zonas_path, outdir
    ):
        """
        eventos_compliance.jsonl solo debe tener los campos que acepta
        el validador del módulo 8 (Paula).
        """
        from pipeline import GondolaPipeline

        GondolaPipeline(
            video_source=str(video_sintetico),
            zonas_path=zonas_path,
            outdir=outdir,
            max_frames=10,
        ).run()

        campos_permitidos = {
            "track_id", "zone_id", "product_id",
            "event_type", "dwell_time_s", "timestamp", "bbox",
        }

        registros = self._leer_jsonl(outdir / "eventos_compliance.jsonl")
        for registro in registros:
            campos_extra = set(registro.keys()) - campos_permitidos
            assert not campos_extra, (
                f"Campos no permitidos en eventos_compliance: {campos_extra}"
            )

    def test_no_se_guardan_frames_del_video(
        self, video_sintetico, zonas_path, outdir
    ):
        """El pipeline no debe guardar ningún frame de imagen del video."""
        from pipeline import GondolaPipeline

        GondolaPipeline(
            video_source=str(video_sintetico),
            zonas_path=zonas_path,
            outdir=outdir,
            max_frames=5,
        ).run()

        extensiones_imagen = {".jpg", ".jpeg", ".png", ".bmp", ".avi", ".mp4"}
        # El heatmap.png es métricas visuales, no un frame del video: se permite
        archivos_imagen = [
            f for f in outdir.rglob("*")
            if f.suffix.lower() in extensiones_imagen
            and f.name != "heatmap.png"
        ]
        assert not archivos_imagen, (
            f"Se guardaron imágenes del video (posible violación de privacidad): "
            f"{archivos_imagen}"
        )
