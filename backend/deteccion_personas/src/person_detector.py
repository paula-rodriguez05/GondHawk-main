"""
person_detector.py
Modulo de Deteccion de Personas - GondHawk (Reto Gondola Inteligente)
Integrante 2 (Deteccion de personas)

Responsabilidad de este modulo (segun la guia del reto):
  - Reconocer personas en cada cuadro del video usando YOLO (Ultralytics).
  - NO guarda ni analiza caras. Solo entrega la posicion (bounding box) de
    cada persona detectada en cada frame, para que el integrante 3
    (Tracking) le asigne un ID y arme las trayectorias.

Cumplimiento de privacidad (Ley 1581 de 2012):
  - Este modulo nunca recorta, guarda ni procesa la region facial.
  - No se hace ningun tipo de reconocimiento facial ni biometrico.
  - Solo se conserva: bounding box, confianza y clase ("person").

Sobre el umbral de confianza
----------------------------
El umbral por defecto baja de 0.40 a 0.25 tras medirlo sobre escenas
sinteticas 3D: con 0.40 el detector encontraba 1703 personas donde habia unas
6000, y las detecciones intermitentes fragmentaban los tracks hasta el punto
de que nadie alcanzaba el umbral de permanencia. YOLO SI ve las figuras, pero
con confianza baja porque fue entrenado sobre fotografias y las figuras
renderizadas no tienen textura ni detalle fotografico.

El compromiso es explicito: un umbral bajo agrega falsos positivos, pero en
este pipeline la etapa de tracking descarta lo que no persiste entre frames,
mientras que una deteccion perdida no la recupera nadie. Para video real
grabado en tienda, 0.35-0.45 sigue siendo lo adecuado; el perfil "sintetico"
existe para no tener que recordar esto cada vez.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional
import warnings

import numpy as np
from ultralytics import YOLO

# En el dataset COCO (con el que viene entrenado YOLO por defecto),
# la clase 0 es "person". Filtramos solo esa clase.
PERSON_CLASS_ID = 0

# Raiz del proyecto (GondHawk-main), calculada desde este archivo para que
# el path del modelo no dependa de la maquina/usuario donde se clone el repo.
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_MODELO_SINTETICO = _PROJECT_ROOT / "runs" / "detect" / "train" / "weights" / "best.pt"


def _es_checkpoint_disponible(path: Path) -> bool:
    if not path.is_file():
        return False

    with path.open("rb") as archivo:
        return not archivo.read(128).startswith(
            b"version https://git-lfs.github.com/spec/v1"
        )

# Perfiles de deteccion segun el origen del video.
PERFILES = {
    # Video grabado en tienda: la textura y la iluminacion reales dan
    # confianzas altas, asi que se puede exigir mas y evitar falsos positivos.
    "real": {"conf": 0.40, "iou": 0.50, "imgsz": 640},
    # Escena sintetica renderizada: ahora con un modelo entrenado específicamente
    # sobre figuras 3D, podemos subir la confianza y mejorar la precisión.
    "sintetico": {
    "conf": 0.35,
    "iou": 0.45,
    "imgsz": 960,
    "model": str(_MODELO_SINTETICO),
},
    # Para diagnosticar: acepta casi todo. Sirve para saber si el detector
    # "ve" algo o no ve nada, no para producir metricas.
    "permisivo": {"conf": 0.10, "iou": 0.45, "imgsz": 960},
}


@dataclass
class Detection:
    """Una deteccion de persona en un frame (formato acordado con el equipo)."""

    bbox: List[float]  # [x1, y1, x2, y2] en pixeles, esquina sup-izq / inf-der
    confidence: float
    cls: str = "person"

    def to_dict(self) -> dict:
        return {
            "bbox": [round(float(v), 1) for v in self.bbox],
            "confidence": round(float(self.confidence), 4),
            "class": self.cls,
        }


class PersonDetector:
    """Envoltorio simple sobre YOLO de Ultralytics para detectar personas."""

    def __init__(
        self,
        model_path: str = "yolov8n.pt",
        conf_threshold: float = 0.25,
        iou_threshold: float = 0.45,
        device: Optional[str] = None,
        imgsz: int = 640,
        perfil: Optional[str] = None,
        min_area: float = 0.0,
    ):
        """
        Args:
            model_path: pesos de YOLO. "yolov8n.pt" se descarga automaticamente
                la primera vez (modelo liviano, bueno para prototipo/CPU).
                "yolov8s.pt" detecta bastante mejor a costa de ~2.5x tiempo:
                vale la pena si el equipo aguanta.
            conf_threshold: confianza minima para aceptar una deteccion.
            iou_threshold: umbral de IoU para el Non-Max Suppression interno.
            device: "cpu", "cuda", "cuda:0", etc. None deja que Ultralytics elija.
            imgsz: resolucion de inferencia. Subirla ayuda con personas
                pequenas al fondo, que es justo donde se pierden las visitas a
                las gondolas del fondo del pasillo.
            perfil: "real", "sintetico" o "permisivo". Si se indica, sobrescribe
                conf, iou e imgsz con los valores del perfil. Si el perfil
                define una clave "model", se usa ese modelo en lugar del
                model_path proporcionado.
            min_area: area minima del bbox en pixeles cuadrados. Descarta
                detecciones diminutas que casi siempre son ruido y que el
                tracker no consigue seguir.
        """
        # Aplicar perfil si se especifica
        if perfil is not None:
            if perfil not in PERFILES:
                raise ValueError(
                    f"Perfil desconocido: {perfil}. Opciones: {list(PERFILES)}"
                )
            ajustes = PERFILES[perfil]
            conf_threshold = ajustes["conf"]
            iou_threshold = ajustes["iou"]
            imgsz = ajustes["imgsz"]
            # Si el perfil tiene un modelo específico, actualiza model_path
            if "model" in ajustes:
                modelo_perfil = Path(ajustes["model"])
                if _es_checkpoint_disponible(modelo_perfil):
                    model_path = str(modelo_perfil)
                else:
                    warnings.warn(
                        f"No se encontró un checkpoint descargado para el perfil "
                        f"{perfil!r} en {modelo_perfil}. Se usará {model_path!r}; "
                        "Ultralytics lo descargará si aún no está en caché.",
                        UserWarning,
                        stacklevel=2,
                    )

        self.model = YOLO(model_path)
        self.conf_threshold = conf_threshold
        self.iou_threshold = iou_threshold
        self.device = device
        self.imgsz = imgsz
        self.perfil = perfil
        self.min_area = min_area

        # Contadores para diagnostico: si las detecciones caen, lo primero que
        # hay que saber es si el detector no ve nada o si se estan filtrando.
        self.total_detectadas = 0
        self.total_descartadas_por_area = 0

    def detect_frame(self, frame: np.ndarray) -> List[Detection]:
        """Detecta personas en un solo frame (numpy array BGR, como los da OpenCV).

        Returns:
            Lista de Detection ordenada como la entrega el modelo.
        """
        results = self.model.predict(
            source=frame,
            classes=[PERSON_CLASS_ID],
            conf=self.conf_threshold,
            iou=self.iou_threshold,
            imgsz=self.imgsz,
            device=self.device,
            verbose=False,
        )[0]

        detections: List[Detection] = []
        if results.boxes is None:
            return detections

        for box in results.boxes:
            xyxy = box.xyxy[0].tolist()
            conf = float(box.conf[0])

            if self.min_area > 0:
                ancho = xyxy[2] - xyxy[0]
                alto = xyxy[3] - xyxy[1]
                if ancho * alto < self.min_area:
                    self.total_descartadas_por_area += 1
                    continue

            detections.append(Detection(bbox=xyxy, confidence=conf))

        self.total_detectadas += len(detections)
        return detections

    def resumen(self) -> dict:
        """Estadisticas de la corrida, utiles para comparar configuraciones."""
        return {
            "modelo": getattr(self.model, "model_name", "yolov8"),
            "perfil": self.perfil,
            "conf_threshold": self.conf_threshold,
            "iou_threshold": self.iou_threshold,
            "imgsz": self.imgsz,
            "total_detectadas": self.total_detectadas,
            "descartadas_por_area": self.total_descartadas_por_area,
        }