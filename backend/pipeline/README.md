# Módulo 6 — Backend / Pipeline

**Integrante:** Laura  
**Fecha de entrega:** 2 de septiembre  
**Dependencias:** módulos 1 (Nicol), 2 (Samuel), 3 (Juan), 4 (Arturo) y 5 (Diego) deben estar listos.

---

## Qué hace este módulo

Junta todos los módulos del proyecto en un único flujo local. El video entra,
pasa por detección, tracking, heatmap, tiempo de permanencia y detección de
eventos, y al final quedan todas las métricas guardadas en `pipeline/output/`.

**No depende de la nube.** Todo corre localmente en el mismo equipo.

Flujo de datos (según la guía del reto, sección 3):

```
Video
  │
  ▼
[Módulo 2 — Samuel]  Detección de personas (YOLO)
  │  detecciones.jsonl
  ▼
[Módulo 3 — Juan]    Tracking (ByteTrack)
  │  tracking.jsonl
  ├──────────────────────────────┐
  ▼                              ▼
[Módulo 4 — Arturo]  Heatmap    [Módulo 5 — Diego]  Tiempo de permanencia
  │  heatmap.png                  │  dwell_time.jsonl
  │  conteo_zonas.json            │
  └──────────────┬────────────────┘
                 ▼
         [Módulo 1 — Nicol]  Detección de eventos
                 │  eventos_interaccion.jsonl
                 │  eventos_compliance.jsonl
                 │  metricas_interaccion.json
                 ▼
         [Módulo 6 — Laura]  Pipeline (este módulo)
                 │  metricas_pipeline.json
                 ▼
         [Módulo 7 — Roa]    Dashboard  (lee las métricas)
```

---

## Archivos de salida

Todos se generan en `pipeline/output/`:

| Archivo | Descripción |
|---|---|
| `detecciones.jsonl` | Salida del módulo 2 (Samuel): bounding boxes por frame |
| `detecciones.meta.json` | Metadatos del video (fps, resolución, frames) |
| `tracking.jsonl` | Salida del módulo 3 (Juan): tracks con person_id |
| `dwell_time.jsonl` | Salida del módulo 5 (Diego): tiempo por zona |
| `eventos_interaccion.jsonl` | Salida del módulo 1 (Nicol): formato canónico |
| `eventos_compliance.jsonl` | Proyección para el validador del módulo 8 (Paula) |
| `metricas_interaccion.json` | Embudo por góndola (visitas, paradas, tomas, devoluciones) |
| `heatmap.png` | Mapa de calor (módulo 4 — Arturo) |
| `heatmap_matrix.npy` | Matriz suavizada del heatmap |
| `heatmap_raw.npy` | Matriz cruda del heatmap |
| `conteo_zonas.json` | Visitas únicas y % tiempo ocupado por zona |
| `metricas_pipeline.json` | Resumen global del pipeline |

---

## Cómo ejecutar

> **Importante:** todos los comandos de esta guía se corren desde la **raíz del repositorio**
> (la carpeta `GondHawk-main`, la que contiene `pipeline/`, `data/`, `mapas_de_calor/`, etc.),
> no desde dentro de `pipeline/`. Si al hacer `cd GondHawk-main` PowerShell te dice que la ruta
> no existe, es porque ya estabas parado ahí — revisa el prompt (`PS C:\...\GondHawk-main>`)
> antes de repetir el `cd`.

### Instalación de dependencias

```bash
# Desde la raíz del proyecto
pip install -r pipeline/requirements.txt
```

### Ejecución básica

```bash
python pipeline/src/pipeline.py --video data/vtest.avi
```

### Con todas las opciones

```bash
python pipeline/src/pipeline.py \
    --video data/vtest.avi \
    --zonas mapas_de_calor/config/zonas.json \
    --productos pipeline/config/productos.json \
    --outdir pipeline/output \
    --t0 2026-08-20T09:00:00 \
    --min-dwell 2.0 \
    --gracia-frames 5 \
    --modo-alcance geometrico \
    --colormap turbo \
    --max-frames 500
```

### Prueba rápida (primeros 100 frames)

```bash
python pipeline/src/pipeline.py --video data/vtest.avi --max-frames 100
```

> **Nota:** con `data/vtest.avi` (el video de prueba genérico de peatones) es normal ver
> `0 tomas → 0 devoluciones` y `0.0%` de tasa de interacción. Ese video no tiene gente
> interactuando con estantes reales, así que esta corrida solo confirma que el flujo completo
> (detección → tracking → heatmap → dwell time → eventos → métricas) corre sin errores.
> Con el dataset real o sintético del reto sí deberían aparecer tomas y devoluciones.

---

## Opciones disponibles

| Opción | Default | Descripción |
|---|---|---|
| `--video` | *(requerido)* | Ruta al video o `0` para webcam |
| `--zonas` | `mapas_de_calor/config/zonas.json` | Fuente única de zonas |
| `--productos` | *(ninguno)* | JSON con mapa zone_id → SKU |
| `--outdir` | `pipeline/output` | Carpeta de salida |
| `--t0` | `2026-08-20T09:00:00` | Hora real de inicio del video |
| `--min-dwell` | `2.0` | Segundos mínimos para considerar parada |
| `--gracia-frames` | `5` | Frames sin ver un track antes de cerrar episodio |
| `--modo-alcance` | `geometrico` | Señal de alcance: `geometrico` o `pose` |
| `--model` | `yolov8n.pt` | Pesos de YOLO |
| `--conf` | `0.4` | Umbral de confianza YOLO |
| `--colormap` | `turbo` | Colormap del heatmap |
| `--max-frames` | *(sin límite)* | Útil para pruebas rápidas |

---

## Tests

```bash
# Desde la raíz del proyecto
python -m pytest pipeline/tests/test_pipeline.py -v
```

> Usa `python -m pytest` en vez de `pytest` a secas. En varias instalaciones de Python en
> Windows (sobre todo las de Microsoft Store / `pythoncore`), el ejecutable `pytest.exe` no
> queda agregado al PATH aunque `pip install pytest` diga "already satisfied". `python -m pytest`
> evita ese problema porque llama al módulo directamente con el mismo intérprete que usa `pip`.

Los tests verifican:
- Que todos los módulos se importan correctamente.
- Que se generan todos los archivos de salida.
- Que el formato JSONL es correcto.
- Que las métricas son coherentes (sin negativos, tasas entre 0 y 1).
- Que no se guardan datos que puedan identificar personas (privacidad).

---

## Cumplimiento de privacidad (Ley 1581 de 2012)



- **No se guarda ningún frame del video.**
- **No se guardan recortes de personas ni datos biométricos.**
- Los `track_id` son IDs opacos de ByteTrack: no permiten identificar a nadie.
- `eventos_compliance.jsonl` contiene solo los 7 campos permitidos por el
  validador del módulo 8 (Paula), sin bbox ni ningún campo que aproxime la posición corporal.
- El heatmap es una visualización de densidades numéricas, no una imagen del video.

---

## Notas de integración

- **Fuente única de zonas:** este módulo usa `mapas_de_calor/config/zonas.json`
  como única fuente de verdad, igual que los módulos 1, 4 y 5.
  Ver [INTEGRACION.md](../INTEGRACION.md), punto 3.

- **Resolución del tracker:** se lee automáticamente del video, no está
  quemada en el código. Resuelve el problema reportado en
  [INTEGRACION.md](../INTEGRACION.md), punto 5.

- **Compatibilidad con el validador del módulo 8:** `eventos_compliance.jsonl`
  solo incluye los campos que acepta el validador. El resto de los campos
  canónicos (confianza, detalle, episodio_id) van solo en
  `eventos_interaccion.jsonl`. Ver [INTEGRACION.md](../INTEGRACION.md), punto 2.

---

## Solución de problemas

| Síntoma | Causa | Solución |
|---|---|---|
| `cd GondHawk-main` dice que la ruta no existe | Ya estabas parado dentro de esa carpeta | Revisa el prompt (`PS C:\...\GondHawk-main>`) antes de repetir el `cd` |
| `pytest` no se reconoce como comando, aunque `pip install pytest` diga "already satisfied" | El `.exe` de pytest no quedó en el PATH (típico en Python de Microsoft Store en Windows) | Usa `python -m pytest pipeline/tests/test_pipeline.py -v` |
| `pip install -r pipeline/requirements.txt` no encuentra `ultralytics` | Entorno sin acceso a internet (por ejemplo un sandbox aislado) | Ejecuta la instalación en tu máquina local con conexión a internet |
| `0 tomas → 0 devoluciones` con `data/vtest.avi` | Ese video de prueba no tiene interacciones reales con estantes | Es el comportamiento esperado; usa el dataset real/sintético del reto para ver tomas y devoluciones |
---

## Novedades del backend (4 de septiembre)

### Escalado de zonas
`zonas.json` está dibujado sobre 768x576. Antes se aplicaba tal cual a
cualquier video, así que en 1080p las zonas cubrían el 9% del frame, todas en
la esquina: por eso el overlay del heatmap parecía una plantilla fija. Ahora se
reproyectan a la resolución real (`preproceso.escalar_zonas`).

### Anonimización
Se difumina la región de cabeza de cada persona detectada antes de guardar
cualquier imagen. No usa detección de rostros a propósito: localizar una cara
es computar el dato biométrico que el reto excluye.

    --sin-anonimizar          desactiva (NO usar con personas reales)
    --modo-anonimizacion      blur | pixelado | solido

### Verificación de escena
Rechaza videos que no son de una superficie comercial antes de gastar la
inferencia. Heurística geométrica, no un clasificador entrenado; hay que
presentarlo así.

    --umbral-escena 0.45      puntaje mínimo
    --sin-verificar-escena    omite la verificación

### Video anotado
Genera `video_anotado.mp4` con cajas, IDs de color estable, estelas de
trayectoria, marcadores de TOMA/DEVUELVE y rostros difuminados.

    --sin-video-anotado       no generarlo

### Rendimiento
    --frame-skip 3            procesa 1 de cada 3 frames

A 30 fps no cambia las métricas (nadie cruza una góndola en 33 ms) y divide por
tres el tiempo de inferencia. La API lo usa por defecto.

### Historial
Cada análisis queda en `output/analisis/<id>/` con su propio resumen, indexado
en `output/indice.json`. Endpoints nuevos:

    GET    /api/analisis                              lista + estadísticas
    GET    /api/analisis/{id}                          detalle
    GET    /api/analisis/{id}/archivo/{nombre}         heatmap, video, JSON
    DELETE /api/analisis/{id}                          eliminar
