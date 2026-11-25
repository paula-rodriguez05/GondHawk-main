# Deteccion de personas — GondHawk (Reto Gondola Inteligente)

**Integrante 2 (Samuel)** — Entrega: 24 de agosto

Este modulo reconoce personas en el video de la tienda usando **YOLO
(Ultralytics)**. Por cada frame entrega la posicion (bounding box) de cada
persona detectada. No guarda ni analiza caras, ni hace ningun tipo de
reconocimiento facial: solo posiciones, para cumplir con la Ley 1581 de
2012.

Este es el primer eslabon del pipeline (`2 → 3 → (4 y 5) → 1 → 6 → 7`): sin
esto, el modulo de Tracking (integrante 3) no tiene nada que seguir.

## 1. Instalacion

```bash
cd deteccion_personas
python -m venv venv
# Windows:
venv\Scripts\activate
# Mac/Linux:
source venv/bin/activate

pip install -r requirements.txt
```

La primera vez que corras el detector, Ultralytics descarga automaticamente
los pesos del modelo (`yolov8n.pt`, ~6 MB) desde GitHub. Necesitas internet
esa primera vez.

## 2. Conseguir un video de prueba

```bash
python data/descargar_video_prueba.py
```

Descarga un video publico de peatones (ver `data/README.md` para mas
detalle, o para usar tu propio video).

## 3. Correr la deteccion

```bash
python src/run_detection.py --source data/vtest.avi --output output/detecciones.jsonl
```

Esto genera:

- `output/detecciones.jsonl` → las detecciones, una linea JSON por frame
  (formato explicado en [`FORMATO_DATOS.md`](FORMATO_DATOS.md), el que va a
  usar el integrante 3 para el tracking).
- `output/detecciones.meta.json` → metadata del video (fps, resolucion,
  cuantos frames, etc).

### Opciones utiles

```bash
# Guardar tambien un video con los bounding boxes dibujados (para verificar
# visualmente que si detecta bien; este video NO se sube al repo)
python src/run_detection.py --source data/vtest.avi --output output/detecciones.jsonl --save-video output/preview.mp4

# Probar rapido con solo 100 frames
python src/run_detection.py --source data/vtest.avi --output output/detecciones.jsonl --max-frames 100

# Ajustar que tan estricta es la deteccion (default 0.4)
python src/run_detection.py --source data/vtest.avi --output output/detecciones.jsonl --conf 0.5

# Probar con la webcam en vivo
python src/run_detection.py --source 0 --output output/webcam.jsonl
```

## 4. Estructura del modulo

```
deteccion_personas/
├── README.md                  ← este archivo
├── FORMATO_DATOS.md            ← formato del JSON que consume Tracking (integrante 3)
├── requirements.txt
├── src/
│   ├── person_detector.py     ← clase PersonDetector (envuelve YOLO)
│   ├── utils.py                ← lectura de video, escritura de JSONL, dibujar boxes
│   └── run_detection.py        ← script principal (CLI)
├── tests/
│   └── test_person_detector.py ← pruebas basicas
├── data/
│   ├── README.md
│   └── descargar_video_prueba.py
└── output/                     ← se genera al correr el script (no se sube al repo)
```

## 5. Pruebas

```bash
python tests/test_person_detector.py
```

Corre dos chequeos: que el formato de salida (bbox/confidence/class) sea el
correcto, y que el pipeline de deteccion corra sin errores sobre un frame de
prueba.

## 6. Notas para el resto del equipo

- El **modelo** usado es `yolov8n.pt` (la version "nano", la mas liviana de
  YOLOv8). Corre bien en CPU, ideal para prototipo. Si mas adelante se
  necesita mas precision se puede cambiar a `yolov8s.pt` o `yolov8m.pt` sin
  tocar el resto del codigo (solo el parametro `--model`).
- Solo se detecta la clase `person` (clase 0 de COCO); el resto de objetos
  se ignora.
- El bounding box va en pixeles absolutos `[x1, y1, x2, y2]`, no
  normalizado. Si el modulo de Tracking necesita otro formato (por ejemplo
  `[x, y, ancho, alto]`), avisen antes de programar el tracker para
  ajustarlo aca y no reescribir despues.
- Privacidad: este modulo esta disenado para NO guardar nunca un recorte de
  imagen de una persona ni datos biometricos, solo coordenadas. Esto facilita
  el trabajo del integrante 8 (cumplimiento) mas adelante.
