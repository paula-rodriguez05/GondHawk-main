# Contrato de datos — Módulo 4 (Mapas de calor y zonas)

## 1. Input: Tracking (módulo 3, Juan) → Mapas de calor (módulo 4)

✅ **Formato REAL confirmado** — es el que emite `tracking/src/run_tracking.py`
(mergeado a main, PR #3, documentado en `tracking/README.md`).

Formato: **JSONL**, una línea por frame.

```json
{"frame_id": 0, "timestamp_ms": 0.0, "tracks": [
  {"person_id": 1, "bbox": [640.4, 240.4, 683.9, 322.8], "class": "person"}
]}
```

Campos:
- `frame_id` (int): índice de frame, coincide con el del módulo 2.
- `timestamp_ms` (float): ms desde el inicio del video (NO es hora del día).
- `tracks[].person_id` (int): ID anónimo asignado por ByteTrack (NO es identidad real).
- `tracks[].bbox` (list[float]): `[x1, y1, x2, y2]` en píxeles sin normalizar.
- `tracks[].centroid`: **no viene** en el formato de Juan; este módulo lo deriva del
  bbox como punto medio (ver `trajectory_reader.py`). Si Juan lo agrega a futuro,
  se usa el que venga.

### Normalización de IDs (acuerdo con el módulo 8)
Este módulo convierte `person_id` (int) → `track_id` (str). `str(person_id)` **siempre
pasa** el regex del validador de Paula (`^[0-9a-fA-F]{1,8}(-...){0,4}$`), porque los
dígitos son caracteres hexadecimales válidos. Sin conflicto de integración.

### Metadata
El FPS se obtiene de `deteccion_personas/output/detecciones.meta.json` (igual que hace
Juan). vtest.avi: 768x576 @ 10 fps, 795 frames.

## 2. Output de este módulo (→ módulo 1 Nicol y módulo 6 Laura)

### 2.1 Definición de zonas — `config/zonas.json`
Polígonos en coordenadas de píxeles sobre el frame de referencia del video.

```json
{
  "video_ref": "vtest.avi",
  "frame_width": 768,
  "frame_height": 576,
  "zonas": [
    {"zone_id": "gondola_A1", "poligono": [[10,50],[150,50],[150,300],[10,300]]},
    {"zone_id": "gondola_A2", "poligono": [[160,50],[300,50],[300,300],[160,300]]},
    {"zone_id": "gondola_A3", "poligono": [[310,50],[450,50],[450,300],[310,300]]},
    {"zone_id": "pasillo_central", "poligono": [[10,310],[600,310],[600,400],[10,400]]},
    {"zone_id": "gondola_B1", "poligono": [[460,50],[600,50],[600,300],[460,300]]}
  ]
}
```

**Importante:** los `zone_id` coinciden exactamente con el catálogo que usa Paula
(módulo 8): `gondola_A1`, `gondola_A2`, `gondola_A3`, `pasillo_central`, `gondola_B1`.
Si el equipo agrega zonas nuevas, deben registrarse aquí y avisar a Paula y a Nicol.

### 2.2 Conteos por zona — `output/conteo_zonas.json`
```json
{
  "video_ref": "vtest.avi",
  "frames_procesados": 800,
  "zonas": [
    {"zone_id": "gondola_A1", "visitas_unicas": 12, "frames_ocupada": 340, "pct_tiempo_ocupada": 42.5}
  ]
}
```
- `visitas_unicas`: número de `person_id` distintos que pasaron por la zona.
- `frames_ocupada`: frames en los que hubo al menos un centroide dentro del polígono.
- `pct_tiempo_ocupada`: `frames_ocupada / frames_procesados`, donde `frames_procesados`
  es el número de frames **con al menos un track** (frames con datos), NO el total de
  frames del archivo. El dashboard debe interpretarlo como "% del tiempo con tránsito
  en que la zona estuvo ocupada".
- No se guarda ningún bbox ni imagen que permita identificar a una persona: son agregados.

### 2.3 Mapa de calor — `output/heatmap.png` (+ matrices `.npy`)
Imagen de densidad de flujo (colormap `turbo` por defecto, con `--colormap` se elige
jet/inferno/hot/magma) superpuesta sobre un frame de referencia, con las zonas fuera del
layout atenuadas y los bordes de zona coloreados según calor (rojo >50% ocupación).
La normalización visual usa **escala logarítmica + clipping al percentil 95** para que un
punto muy caliente no aplaste el resto del mapa a azul (ajustable con `--clip-percentile`).

Se guardan dos matrices numéricas:
- `heatmap_matrix.npy`: **suavizada** (Gaussian blur) — para visualización en el dashboard (módulo 7).
- `heatmap_raw.npy`: **cruda, sin suavizar** — para umbrales exactos en el módulo 1 (Nicol, eventos).

## 3. Principio de privacidad aplicado (Ley 1581 de 2012)
- Nunca se persiste ningún crop de imagen de una persona, solo centroides numéricos.
- El heatmap es una agregación de densidad; a partir de él no se puede reconstruir la
  identidad ni la trayectoria individual de una persona.
- `person_id`/`track_id` se trata como opaco: este módulo no lo cruza con ninguna otra
  fuente de datos. Los IDs de ByteTrack representan la identidad de un track dentro de
  la secuencia visible, no una identificación biométrica (limitación documentada por Juan).

## 4. Coordinación con el módulo 5 (Diego) — Tiempo de permanencia

**Entregamos el mismo día (29 ago) y consumimos EXACTAMENTE la misma entrada**
(el `tracking.jsonl` de Juan). Para que los módulos 1 (Nicol) y 6 (Laura) puedan cruzar
nuestras salidas, acordamos estas reglas comunes ANTES de que Diego programe.

### 4.1 Fuente única de zonas
- `config/zonas.json` (este módulo) es la **fuente de verdad** de los polígonos y `zone_id`.
- Diego debe leer ESE archivo, NO definir sus propios polígonos. Si ambos usáramos zonas
  distintas, dwell y heatmap medirían layouts diferentes y no coincidirían.
- Catálogo oficial de `zone_id`: `gondola_A1`, `gondola_A2`, `gondola_A3`, `pasillo_central`,
  `gondola_B1` (alineado con el módulo 8 de Paula).

### 4.2 Regla de pertenencia a una zona (compartida)
- Centroide de la persona = punto medio del bbox: `((x1+x2)/2, (y1+y2)/2)`.
- Una persona está "dentro" de una zona si su centroide cae dentro del polígono (ray casting).
- Es un estado binario por frame por zona (el mismo criterio que usa este módulo).

### 4.3 Normalización de IDs
- Juan entrega `person_id` (entero). Ambos módulos deben convertirlo a `track_id` string:
  `str(person_id)`. Esto pasa el validador del módulo 8 (Paula) — los dígitos son hex válidos.

### 4.4 Salida esperada del módulo 5 (dwell) — para que encaje con Paula/Nicol
Formato propuesto: **JSONL**, un registro por (persona, zona, episodio de permanencia):

```json
{"track_id": "3", "zone_id": "gondola_A3", "dwell_time_s": 14.2, "timestamp_ms": 4733.4, "detuvo": true}
```
- `track_id` (str): ID normalizado como en 4.3.
- `zone_id` (str): del catálogo en 4.1.
- `dwell_time_s` (float ≥ 0): segundos con el centroide dentro del polígono.
- `timestamp_ms` (float): instante de referencia (inicio o fin del episodio — documentar cuál).
- `detuvo` (bool): si `dwell_time_s` supera el umbral definido por Diego (sugerido: ≥ 2 s).
  Este campo le sirve a Nicol para distinguir "pasa de largo" de "se detiene".

Estos campos coinciden con el esquema de eventos del módulo 8 (Paula):
`track_id`, `zone_id`, `dwell_time_s` — así el pipeline de Laura los une sin fricción.
