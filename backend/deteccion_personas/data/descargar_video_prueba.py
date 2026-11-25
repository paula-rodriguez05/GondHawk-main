"""
Descarga un video publico de prueba (peatones caminando, uso academico
estandar de OpenCV) para probar el detector sin necesidad de grabar nada.

Uso:
    python data/descargar_video_prueba.py
"""

import urllib.request
from pathlib import Path

URL = "https://raw.githubusercontent.com/opencv/opencv/master/samples/data/vtest.avi"
DEST = Path(__file__).parent / "vtest.avi"

if __name__ == "__main__":
    print(f"Descargando video de prueba desde:\n  {URL}")
    urllib.request.urlretrieve(URL, DEST)
    print(f"Listo: {DEST}")
