# GondHawk - Tracking de Personas

Módulo de seguimiento multiobjeto de personas para GondHawk.

Este módulo recibe las detecciones de personas generadas por el módulo de detección y utiliza ByteTrack para asignar identificadores persistentes (`person_id`) entre frames.

## Flujo del módulo

```text
Video
  |
  v
Detección de personas (YOLOv8)
  |
  v
detecciones.jsonl
  |
  v
Tracking (ByteTrack)
  |
  v
tracking.jsonl
  |
  v
Análisis temporal
```

## Estructura

```text
tracking/
├── README.md
├── requirements.txt
├── src/
│   ├── tracker.py
│   ├── run_tracking.py
│   └── time_analysis.py
└── tests/
    └── test_tracker.py
```

## Requisitos

- Python 3.10+
- Ultralytics
- NumPy
- LAP

Instalar las dependencias:

```bash
python -m pip install -r tracking/requirements.txt
```

## Funcionamiento

El módulo recibe un archivo JSONL producido por `deteccion_personas`.

Cada línea representa un frame y contiene las personas detectadas:

```json
{
  "frame_id": 0,
  "timestamp_ms": 0.0,
  "detections": [
    {
      "bbox": [640.4, 240.4, 683.9, 322.8],
      "confidence": 0.8369,
      "class": "person"
    }
  ]
}
```

ByteTrack utiliza estas detecciones para asociar las personas entre frames y mantener un identificador persistente mientras la trayectoria pueda ser asociada correctamente.

La salida contiene:

```json
{
  "frame_id": 0,
  "timestamp_ms": 0.0,
  "tracks": [
    {
      "person_id": 1,
      "bbox": [640.4, 240.4, 683.9, 322.8],
      "class": "person"
    }
  ]
}
```

### Campos de salida

| Campo | Descripción |
| --- | --- |
| `frame_id` | Identificador del frame |
| `timestamp_ms` | Tiempo del frame en milisegundos |
| `person_id` | ID asignado a la persona por ByteTrack |
| `bbox` | Coordenadas `[x1, y1, x2, y2]` de la persona |
| `class` | Clase detectada, en este módulo `person` |

## Ejecutar el tracking

Desde la raíz del proyecto:

```bash
python tracking/src/run_tracking.py \
  --input deteccion_personas/output/detecciones.jsonl \
  --output tracking/output/tracking.jsonl
```

El FPS se obtiene automáticamente desde el archivo `.meta.json` generado por el módulo de detección.

También se puede especificar manualmente:

```bash
python tracking/src/run_tracking.py \
  --input deteccion_personas/output/detecciones.jsonl \
  --output tracking/output/tracking.jsonl \
  --frame-rate 10
```

## Prueba rápida

Para procesar solamente una cantidad limitada de frames:

```bash
python tracking/src/run_tracking.py \
  --input deteccion_personas/output/detecciones.jsonl \
  --output tracking/output/tracking_test.jsonl \
  --max-frames 10
```

Una ejecución de prueba con 10 frames produjo:

```text
FPS utilizado: 10.0
Frames procesados: 10
Tracks generados: 30
Personas únicas identificadas: 3
```

## Configuración del tracker

El módulo permite configurar diferentes parámetros de ByteTrack.

### `--track-buffer`

Indica cuántos frames puede permanecer perdido un track antes de eliminarse.

Valor predeterminado:

```text
30 frames
```

Ejemplo:

```bash
python tracking/src/run_tracking.py \
  --input deteccion_personas/output/detecciones.jsonl \
  --output tracking/output/tracking.jsonl \
  --track-buffer 30
```

### `--frame-rate`

Permite especificar manualmente los FPS del video.

```bash
python tracking/src/run_tracking.py \
  --input deteccion_personas/output/detecciones.jsonl \
  --output tracking/output/tracking.jsonl \
  --frame-rate 10
```

Si no se especifica, el módulo intenta obtener el FPS desde el archivo de metadata de detección.

## Análisis temporal

El módulo incluye `time_analysis.py`, que permite analizar la cantidad de personas únicas observadas en diferentes intervalos de tiempo.

Ejemplo:

```bash
python tracking/src/time_analysis.py \
  --input tracking/output/tracking.jsonl \
  --interval 5
```

Ejemplo de salida:

```text
========== ANALISIS TEMPORAL ==========
Personas únicas: 10
Intervalo: 5.0 segundos

[0.0s - 5.0s] personas únicas: 8 IDs: [1, 2, 3, 4, 5, 6, 7, 8]
[5.0s - 10.0s] personas únicas: 8 IDs: [2, 4, 5, 6, 7, 8, 9, 10]

Franja con más visitas: 0.0s - 5.0s (8 personas)
========================================
```

## Validación realizada

El módulo fue probado utilizando el video de prueba `vtest.avi`.

Características del video:

```text
Resolución: 768x576
FPS: 10
Frames: 795
Duración aproximada: 79.5 segundos
```

Resultados obtenidos:

```text
Frames procesados:       795
Detecciones de entrada:  4576
Tracks generados:        4478
Personas únicas:         31
```

La ejecución completa confirmó que el tracker puede mantener identificadores persistentes durante las trayectorias visibles de las personas a lo largo del video.

## Limitaciones

El tracking multiobjeto no garantiza que un `person_id` permanezca idéntico durante toda la aparición de una persona.

Un ID puede cambiar cuando:

- una persona queda parcial o completamente ocluida;
- una detección desaparece durante varios frames;
- varias personas se encuentran muy próximas;
- una persona aparece muy lejos y ocupa pocos píxeles;
- el detector no consigue detectar correctamente a una persona;
- una persona sale y vuelve a entrar en la escena.

La calidad final del tracking depende directamente de la calidad de las detecciones proporcionadas por YOLOv8.

Por esta razón, los `person_id` representan la identidad de un track dentro de la secuencia visible, y no una identificación biométrica de la persona.

## Salidas

Los archivos generados durante las pruebas se almacenan en:

```text
tracking/output/
```

Esta carpeta está incluida en `.gitignore` para evitar subir archivos generados automáticamente al repositorio.

## Tecnologías utilizadas

- **Python**
- **Ultralytics**
- **YOLOv8**
- **ByteTrack**
- **NumPy**
- **LAP**

## Integración con GondHawk

Este módulo consume la salida generada por `deteccion_personas` y genera información estructurada sobre las trayectorias de las personas.

La información generada puede ser utilizada posteriormente por otros módulos de GondHawk para:

- análisis de permanencia;
- conteo de personas;
- análisis temporal;
- identificación de zonas de mayor tránsito;
- análisis de comportamiento;
- generación de recomendaciones.

## Estado del módulo

**Implementado y validado.**

El módulo actualmente permite:

- Recibir detecciones en formato JSONL.
- Asignar `person_id` mediante ByteTrack.
- Mantener IDs entre frames.
- Procesar videos completos mediante JSONL.
- Configurar FPS.
- Configurar `track_buffer`.
- Limitar frames para pruebas.
- Generar salida JSONL.
- Realizar análisis temporal.
- Validar el funcionamiento con un video de prueba.
