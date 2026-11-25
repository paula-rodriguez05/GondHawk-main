# Módulo 4 — Mapas de calor y zonas (Arturo)

**Reto:** Góndola Inteligente — HackTech 5.0 2026 (Scapder) · Equipo Ship Club
**Entrega:** 29 de agosto
**Input:** JSONL de tracking del módulo 3 (Juan) — ✅ ya entregado y mergeado a main (PR #3).
**Output:** zonas definidas + mapa de calor de flujo + conteos por zona, consumidos por el
módulo 1 (Nicol, eventos de interacción) y el módulo 6 (Laura, pipeline).

## Estado

✅ **Funcional con datos simulados y listo para el tracking real de Juan.** El lector
(`trajectory_reader.py`) ya consume el formato exacto que emite
`tracking/src/run_tracking.py` (`person_id` entero + bbox, sin centroid).

## Estructura

```
mapas_calor_zonas/
├── config/
│   └── zonas.json              # catálogo de zonas (polígonos), alineado con módulo 8
├── data/                       # aquí va vtest.avi y los JSONL (reales o simulados)
├── output/                     # heatmap.png, matrices .npy, conteo_zonas.json
├── src/
│   ├── zone_definer.py         # herramienta interactiva para dibujar zonas sobre un frame real
│   ├── simulate_trajectories.py# trayectorias falsas con el MISMO formato del tracker de Juan
│   ├── trajectory_reader.py    # lector del JSONL de tracking (normaliza person_id -> track_id)
│   └── heatmap_generator.py    # construye heatmap + conteos por zona
├── tests/
│   └── test_heatmap.py         # tests con datos 100% sintéticos, no requieren video
├── FORMATO_DATOS.md            # contrato de datos: input real de Juan + output de este módulo
└── requirements.txt
```

## Cómo correrlo

```bash
pip install -r requirements.txt

# 1. (Opcional) Datos simulados con el formato exacto de Juan, para probar sin
#    correr deteccion+tracking. Zone-aware: el flujo cruza el pasillo y se
#    desvia a las góndolas.
python src/simulate_trajectories.py --output data/tracking_simulado.jsonl \
    --zonas config/zonas.json --frames 800 --personas 15 --fps 10

# 2. (Opcional) Redefinir las zonas sobre un frame real de vtest.avi
python src/zone_definer.py --video data/vtest.avi --output config/zonas.json

# 3. Generar el heatmap y los conteos por zona
python src/heatmap_generator.py --trayectorias data/tracking_simulado.jsonl \
    --zonas config/zonas.json --output-dir output --frame-ref data/vtest.avi

# 4. Correr los tests
pytest tests/ -v
```

## Con el tracking real de Juan (ya disponible)

```bash
# Juan genera:  python tracking/src/run_tracking.py \
#                 --input deteccion_personas/output/detecciones.jsonl \
#                 --output tracking/output/tracking.jsonl
# Este módulo consume esa salida directamente:
python src/heatmap_generator.py --trayectorias ../tracking/output/tracking.jsonl \
    --zonas config/zonas.json --output-dir output --frame-ref data/vtest.avi
```

Si el formato de Juan cambiara, solo hay que ajustar `trajectory_reader.py` — el resto
del módulo no cambia.

## Detalles técnicos

- **Rendimiento:** la clasificación punto→zona usa máscaras rasterizadas
  (`cv2.fillPoly` + lookup numpy), no geometría en Python: escala a videos largos.
- **Visualización:** normalización log1p + clipping al percentil 95 para que el mapa
  sea legible aunque haya un punto muy caliente (`--clip-percentile` para ajustar).
- **Salidas numéricas:** `heatmap_matrix.npy` (suavizada, para el dashboard) y
  `heatmap_raw.npy` (cruda, para umbrales exactos del módulo 1).

## Privacidad por diseño (Ley 1581 de 2012)

- Nunca se guarda ningún recorte de imagen de una persona: solo centroides numéricos
  y agregados por zona.
- El `person_id` se trata como opaco; este módulo no lo cruza con ninguna otra fuente
  de datos que pudiera reidentificar a alguien.
- La salida (`conteo_zonas.json`, `heatmap.png`) es información agregada de flujo, no
  trayectoria individual reconstruible.

## zone_id oficiales (catálogo, alineado con Paula — módulo 8)

`gondola_A1`, `gondola_A2`, `gondola_A3`, `pasillo_central`, `gondola_B1`.
Si el equipo agrega zonas nuevas, deben registrarse aquí y avisarse a Paula y a Nicol.

## track_id: compatibilidad con el módulo 8 (Paula)

Este módulo convierte `person_id` (int, formato de Juan) a `track_id` string.
`str(person_id)` siempre pasa el regex del validador de Paula (los dígitos son
hex válidos), así que no hay conflicto de integración.
