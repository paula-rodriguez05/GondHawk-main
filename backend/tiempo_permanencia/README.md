# Módulo de Tiempo de Permanencia — GondHawk

**Integrante:** Diego (5)

El módulo **tiempo_permanencia** analiza cuánto tiempo cada persona rastreada
permanece dentro de las zonas de góndola definidas por el equipo, y genera un
JSONL de eventos de permanencia que consumen el backend y los demás módulos
del pipeline.

Este README es la **única** fuente de documentación del módulo.

---

## 1. Propósito del Módulo

Dentro del ecosistema de GondHawk, este módulo:

- **Calcula el tiempo de permanencia** (`dwell_time`) de cada `track` dentro
  de cada zona de góndola definida en el catálogo oficial de zonas del proyecto.
- **Filtra / clasifica ruido** mediante un umbral configurable (`--min-dwell`):
  distingue entre una persona que solo pasó de largo y una que se detuvo.
- **Separa los estados** de entrada y salida de una zona para medir, de forma
  continua, la duración de la estancia.

El flujo del proyecto es: `2 (detección) → 3 (tracking) → 4 y 5 (zonas y
permanencia) → 1 (eventos) → 6 (pipeline) → 7 (dashboard)`.

Este módulo corresponde al paso **5**.

---

## 2. Fuentes de Verdad y Contrato

### 2.1 Entrada: `tracking/output/tracking.jsonl` (Integrante 3)

Generado por el módulo de tracking. Se procesa **línea por línea** (streaming),
sin cargar el archivo completo en memoria. Cada línea tiene la forma:

```json
{
  "frame_id": 0,
  "timestamp_ms": 0.0,
  "tracks": [
    { "person_id": 1, "bbox": [x1, y1, x2, y2], "class": "person" }
  ]
}
```

### 2.2 Referencia temporal: `timestamp_ms`

- **`timestamp_ms` es la única fuente de verdad para calcular el dwell.**
- `frame_id` se **conserva** en `tracking.jsonl` porque forma parte del
  contrato del módulo de tracking, pero **NO participa en el cálculo de
  permanencia** (no se usa `(exit_frame - entry_frame) / fps`). El cálculo se
  basa exclusivamente en `timestamp_ms`.
- Por ello `DwellTimeAnalyzer.process_frame(timestamp_ms, tracks)` **no recibe**
  `frame_id`.

### 2.3 Entrada: catálogo oficial de zonas — fuente única (Integrante 4)

El módulo usa por defecto el archivo unificado:
`mapas_de_calor/config/zonas.json`.

Este archivo es la **única** fuente de verdad de las coordenadas poligonales de
cada zona. El integrante 5 **no** hardcodea zonas. El módulo las carga en
tiempo de ejecución; esto permite reemplazar el archivo por el que genere el
Integrante 4 **sin modificar el código**. Estructura:

```json
{
  "zonas": [
    {"zone_id": "gondola_A1", "poligono": [[x1, y1], [x2, y2], ...]},
    {"zone_id": "pasillo_central", "poligono": [[x1, y1], [x2, y2], ...]}
  ]
}
```

- Los vértices están en **píxeles absolutos** del frame.
- Se soportan polígonos convexos y cóncavos.

### 2.4 Centroide

El punto de anclaje de cada persona es el **punto medio exacto del bbox**:

```text
centroide = ((x1 + x2) / 2, (y1 + y2) / 2)
```

### 2.5 Identificador de track

```text
track_id = str(person_id)
```

### 2.6 Filtrado de clases

El sistema solo detecta y rastrea la clase `person`. Cualquier otra clase
presente en `tracks` se ignora.

---

## 3. Lógica de Funcionamiento

### 3.1 Máquina de estados temporal

Se mantiene un diccionario en memoria con la estructura:

```text
(track_id, zone_id) -> entry_timestamp_ms
```

- **Entrada**: cuando el centroide de un `track` cae dentro de una zona y la
  pareja `(track_id, zone_id)` aún no estaba registrada, se guarda el
  `timestamp_ms` de entrada.
- **Salida**: cuando un `track` deja de verse dentro de la zona (o el video
  finaliza), se calcula:

```text
dwell_ms = current_timestamp_ms - entry_timestamp_ms
```

- **Cierre**: al final del archivo, los tracks aún activos se cierran con el
  último `timestamp_ms` disponible, sin duplicar permanencias.

### 3.2 Validación geométrica con OpenCV

La pertenencia de un punto a una zona se determina con **`cv2.pointPolygonTest`**
(además de NumPy para los polígonos):

```python
result = cv2.pointPolygonTest(polygon, (float(x), float(y)), False)
# result >= 0  -> dentro o en el borde
```

Esto permite evaluar correctamente polígonos irregulares y en diagonal, no
solo rectángulos.

### 3.3 Umbral y campo `detuvo`

Cada evento incluye un booleano `detuvo`:

```text
detuvo = dwell_time_s >= min_dwell
```

El umbral por defecto es `2.0` segundos (configurable con `--min-dwell`).

**Importante:** la salida **emite todos los eventos de permanencia válidos**,
incluidos aquellos con `detuvo: false`. **No existe un filtro externo** que
descartemos los eventos cortos en disco. Por tanto, en `dwell_time.jsonl`
**coexisten** registros con `detuvo: true` y con `detuvo: false`; el consumidor
(backend / Integrante 1) decide cómo usar el flag.

Además, el analizador soporta un margen de tolerancia configurable:
`--gracia-frames`. Si un `track` desaparece momentáneamente de una zona,
se mantiene el evento vivo hasta ese número de frames consecutivos sin visión
antes de cerrarlo formalmente; si reaparece antes de eso, el conteo continúa.

---

## 4. Estructura de la Salida

El resultado se escribe en `output/dwell_time.jsonl`, una línea JSON por
evento. Ejemplo real de una línea:

```json
{"track_id": "1", "zone_id": "gondola_A1", "dwell_time_s": 3.5, "timestamp_ms": 1000.0, "detuvo": true}
```

| Campo             | Tipo    | Descripción                                                     |
|-------------------|---------|-----------------------------------------------------------------|
| `track_id`        | string  | `str(person_id)` — identificador del track                      |
| `zone_id`         | string  | Identificador oficial de la zona donde se registró el dwell     |
| `dwell_time_s`    | float   | Tiempo de permanencia en **segundos** (redondeado a 2 decimales)|
| `timestamp_ms`    | float   | `timestamp_ms` de **entrada** a la zona (inicio del dwell)      |
| `detuvo`          | boolean | `true` si `dwell_time_s >= min_dwell`, `false` en caso contrario|

---

## 5. Instalación

```bash
cd tiempo_permanencia
pip install -r requirements.txt
```

Dependencias: `numpy>=1.26.0`, `opencv-python>=4.9.0`.

---

## 6. Ejecución

Desde la **raíz del proyecto**:

```bash
python tiempo_permanencia/src/dwell_time.py \
    --input tracking/output/tracking.jsonl \
    --zonas mapas_de_calor/config/zonas.json \
    --output tiempo_permanencia/output/dwell_time.jsonl \
    --min-dwell 2.0 \
    --gracia-frames 2
```

Parámetros:

| Parámetro    | Descripción                                        |
|--------------|----------------------------------------------------|
| `--input`    | Ruta a `tracking.jsonl` (salida del Integrante 3)  |
| `--zonas`    | Ruta al catálogo oficial de zonas (default: `mapas_de_calor/config/zonas.json`) |
| `--output`   | Ruta de salida de `dwell_time.jsonl`               |
| `--min-dwell`| Umbral mínimo en segundos (default: `2.0`)         |
| `--gracia-frames` | Frames consecutivos sin ver el track antes de cerrar el dwell (default: `2`) |

---

## 7. Tests

Ejecuta la suite unitaria desde la raíz del proyecto:

```bash
python tiempo_permanencia/test_dwell_time.py
```

Resultado esperado:

```text
Resultados: 14 passed, 0 failed
```

Los 14 tests cubren: entrada/salida antes del umbral (`detuvo: false`),
permanencia mayor e igual al umbral (`detuvo: true`), permanencia hasta el
final del archivo, cambio de una zona a otra, dos personas simultáneas en la
misma zona, zona sin vértices (error explícito), conversión de `person_id` a
`track_id` string, centroide punto medio exacto, y confirmación de que
`frame_id` no es necesario para calcular el dwell.

---

## 8. Privacidad (Ley 1581 de 2012)

- No se guardan imágenes, rostros ni datos biométricos.
- Solo se almacena `track_id` (entero anonimizado como string) y coordenadas
  de `bbox`.
- La permanencia es una métrica de comportamiento agregada, no personal.

---

**Fuente de documentación única:** este archivo.
**Referencias externas:** `FORMATO_DATOS.md` (contrato de datos del proyecto).
