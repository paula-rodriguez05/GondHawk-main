# Notas de integración — GondHawk

**Responsable:** Nicol Arenas · Actualizado: 29 de agosto

Este archivo recoge los puntos donde los módulos no encajan todavía. Todo lo
que está aquí fue verificado ejecutando el código, no leyendo los README.
El orden es por urgencia para la entrega.

---

## 1. El validador del módulo 8 no se puede importar

**Prioridad: alta**

`untitled10.py` viene exportado de Google Colab y repite
`from __future__ import annotations` en la línea 260, después de código
ejecutable. En Colab funciona porque cada celda se ejecuta por separado; como
archivo de Python no compila:

```text
SyntaxError: from __future__ imports must occur at the beginning of the file
```

Ningún módulo puede importar el validador hoy. Además el archivo mezcla tres
cosas en un solo script (validador, generador de datos simulados y motor de
recomendación) y vive suelto en la raíz del repo.

**Propuesta para Paula:** mover a `cumplimiento/src/validador.py`,
`cumplimiento/src/simulador.py` y `cumplimiento/src/recomendador.py`, con un
único `from __future__` al inicio de cada archivo.

Mientras tanto, `deteccion_eventos/tools/verificar_cumplimiento.py` lo carga
quitando los imports repetidos, sin modificar el original.

---

## 2. La salida del módulo 5 no pasa el validador del módulo 8

**Prioridad: alta**

Corriendo el validador de Paula sobre `dwell_time.jsonl` de Diego:

```text
dwell_time.jsonl:  0/121 registros conformes
    121 x Campo no reconocido en el esquema acordado: 'timestamp_ms'
    121 x Campo no reconocido en el esquema acordado: 'detuvo'
```

No es un error de Diego: los dos módulos acordaron esquemas distintos y nadie
los cruzó. El validador acepta solo `track_id`, `zone_id`, `product_id`,
`event_type`, `dwell_time_s`, `timestamp` (ISO 8601) y `bbox`.

**Cómo lo resolvimos en el módulo 1:** dos salidas. El archivo canónico
conserva todo lo que el pipeline necesita (`timestamp_ms`, confianza, detalle)
y un archivo de proyección lleva solo los 7 campos permitidos. Verificado:
59/59 conformes.

**Decisión que hay que tomar en equipo:** o Diego produce también su proyección
de cumplimiento, o se acuerda que el módulo 1 es el único que habla con el
validador y el resto de módulos se quedan en formato interno. La segunda es más
simple y es la que sugiero.

---

## 3. Hay dos `zonas.json` distintos en el repo

**Prioridad: media**

- `mapas_de_calor/config/zonas.json`
- `tiempo_permanencia/zonas.json`

Hoy tienen el mismo contenido, pero son dos archivos: en cuanto alguien mueva
un polígono, el heatmap y el dwell van a estar midiendo layouts diferentes y
nadie se va a dar cuenta hasta la demo.

**Propuesta:** dejar `mapas_de_calor/config/zonas.json` como única fuente
(ya está declarado así en `FORMATO_DATOS.md`) y borrar la copia. El módulo 1 ya
lee de esa ruta.

---

## 4. El README del módulo 5 documenta un esquema que su código no lee

**Prioridad: media**

El README describe:

```json
{"zones": {"gondola_1": {"name": "...", "vertices": [[x, y]]}}}
```

pero `load_zones_from_json()` exige `data["zonas"]` con `poligono`. Quien siga
el README y arme el archivo a mano se estrella. Lo mismo pasa con
`EJEMPLO_SALIDA.jsonl`, que usa `gondola_1`, `gondola_2`, `gondola_3` cuando el
catálogo oficial es `gondola_A1`, `gondola_A2`, `gondola_A3`, `pasillo_central`,
`gondola_B1`.

`deteccion_eventos/src/zonas.py` acepta los dos esquemas a propósito, para que
esto no bloquee a nadie mientras se corrige el README.

---

## 5. El tracking tiene la resolución quemada en el código

**Prioridad: media**

`tracking/src/run_tracking.py`, línea 134:

```python
frame_shape=(576, 768, 3),
```

Sirve para `vtest.avi`, pero el reto dice que Scapder puede facilitar otro
video. Si llega uno de 1080p, el tracker asigna IDs con coordenadas fuera de
rango y las zonas dejan de tener sentido, sin ningún error visible.

**Propuesta para Juan:** leer `frame_width` y `frame_height` de
`deteccion_personas/output/detecciones.meta.json`, que ya los trae.

---

## 6. El módulo 5 fragmenta episodios cuando el tracker parpadea

**Prioridad: baja**

`DwellTimeAnalyzer.process_frame` cierra un episodio en cuanto la pareja
`(track_id, zone_id)` no aparece en un frame. ByteTrack pierde el ID por
oclusión durante uno o dos frames de forma rutinaria, así que una visita de
8 segundos puede quedar registrada como tres permanencias cortas, y las tres
con `detuvo: false`.

Se ve en los datos: 121 eventos de dwell para 40 personas simuladas, con
promedio de 1.7 s.

**Sugerencia para Diego (cambio pequeño):** contador de frames de gracia antes
de cerrar, igual que `--gracia-frames` en el módulo 1. Son unas 6 líneas.

Mientras tanto el módulo 1 no depende de eso: calcula su propia permanencia con
ventana de gracia y usa el archivo de Diego solo para contrastar.

---

## 7. Zonas solapadas: criterio ambiguo

**Prioridad: baja**

`_get_zone_for_point` devuelve la primera zona del diccionario que contenga
el punto, o sea que depende del orden de lectura del JSON. Hoy los polígonos no
se solapan y no se nota, pero en cuanto alguien defina una góndola dentro de un
pasillo el resultado cambia según el orden del archivo.

El módulo 1 resuelve el solape con una regla explícita: la góndola gana sobre
el pasillo, porque lo que interesa es la interacción con el estante, no el
tránsito. Cubierto por `test_gondola_gana_sobre_pasillo_en_solape`.

---

## 8. Lo que sí encaja bien

Vale la pena dejarlo dicho porque son las decisiones que hay que sostener:

- `track_id = str(person_id)` es consistente en los módulos 1, 4 y 5, y pasa el
  regex hexadecimal del validador.
- El centroide como punto medio del bbox es el mismo en los tres módulos que lo
  usan.
- El formato JSONL línea-por-frame permite procesamiento en streaming: ningún
  módulo carga el video entero en memoria. Eso es directamente el criterio de
  viabilidad edge del reto.
- El catálogo de `zone_id` coincide entre el módulo 4 y el validador del
  módulo 8.
