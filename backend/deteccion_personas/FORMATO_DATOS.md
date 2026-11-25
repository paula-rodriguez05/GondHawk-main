# Formato de datos — Deteccion de personas → Tracking

Este es el formato de salida que entrega el modulo de **Deteccion de
personas** (integrante 2) y que consume el modulo de **Tracking**
(integrante 3). Segun la guia del reto, todo el equipo debe usar el mismo
formato desde el dia 1 para no reescribir codigo despues en el pipeline.

Propongo esto para la reunion de la Etapa 0 — se puede ajustar entre todos,
pero hay que dejarlo firmado por escrito antes de que cada quien programe su
parte.

## Archivo de salida: JSONL (una linea JSON por frame)

Ruta tipica: `output/detecciones.jsonl`

Cada linea es un objeto JSON independiente (facil de leer en streaming,
sin tener que cargar todo el video en memoria):

```json
{"frame_id": 0, "timestamp_ms": 0.0, "detections": [{"bbox": [640.4, 240.4, 683.9, 322.8], "confidence": 0.8369, "class": "person"}]}
{"frame_id": 1, "timestamp_ms": 100.0, "detections": [{"bbox": [634.4, 241.6, 682.0, 323.2], "confidence": 0.8091, "class": "person"}]}
```

### Campos

| Campo | Tipo | Descripcion |
| --- | --- | --- |
| `frame_id` | int | Numero de frame, empieza en 0 |
| `timestamp_ms` | float | Tiempo del frame en milisegundos desde el inicio del video |
| `detections` | list | Lista de personas detectadas en ese frame (puede estar vacia) |
| `detections[].bbox` | [x1, y1, x2, y2] | Bounding box en **pixeles**, esquina superior-izquierda y esquina inferior-derecha. Sin normalizar (no es 0-1). |
| `detections[].confidence` | float (0-1) | Confianza de la deteccion |
| `detections[].class` | string | Siempre `"person"` en este modulo |

Importante para el integrante 3 (Tracking): **este modulo no asigna
`person_id`**. Ese ID lo crea el tracker (ByteTrack/DeepSORT) al asociar
detecciones entre frames consecutivos.

## Archivo de metadata: `output/detecciones.meta.json`

Se genera junto al JSONL, con info del video procesado:

```json
{
  "video_source": "data/vtest.avi",
  "fps_origen": 10.0,
  "frame_width": 768,
  "frame_height": 576,
  "frames_procesados": 60,
  "total_detecciones": 246,
  "tiempo_procesamiento_seg": 10.15,
  "modelo": "yolov8n.pt",
  "conf_threshold": 0.4
}
```

Esto le sirve al equipo (backend, dashboard) para saber el FPS y resolucion
originales, necesarios para convertir tiempos y coordenadas mas adelante.

## Privacidad por diseño (Ley 1581 de 2012)

- No se guarda ningun recorte de imagen de la cara ni del cuerpo.
- No se guarda ningun embedding facial ni biometrico.
- Solo se guarda la posicion (bbox) + confianza. Nada que permita
  identificar a una persona especifica.
