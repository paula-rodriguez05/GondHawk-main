# Módulo de Detección de Eventos de Interacción — GondHawk

**Integrante:** Nicol (módulo 1) · **Entrega:** 31 de agosto

Este módulo cierra el embudo físico de compra que pide el reto: convierte las
trayectorias anónimas del tracking en eventos de **aproximación**, **toma de
producto (pick-up)** y **devolución al estante (put-back)**, y con eso calcula
las métricas de space management.

```text
2 detección → 3 tracking → 4 zonas / 5 permanencia → 1 EVENTOS → 6 pipeline → 7 dashboard
                                                      (este módulo)
```

---

## 1. Qué hace

Mantiene una **máquina de estados por persona**. Cada persona que entra a una
zona de góndola abre un *episodio*, y dentro de ese episodio se recorre el
embudo:

```text
FUERA ──entra a góndola──► TRÁNSITO
TRÁNSITO ──dwell ≥ umbral──► DETENIDO           evento: approach
TRÁNSITO ──sale antes del umbral──► FUERA       evento: pass_by
DETENIDO ──alcance válido──► CON_PRODUCTO       evento: pickup
CON_PRODUCTO ──segundo alcance──► DETENIDO      evento: return
CON_PRODUCTO ──sale de la zona──► FUERA         evento: takeaway
```

De ahí salen las cuatro métricas accionables del reto: tasa de detención, tasa
de interacción, **tasa de rechazo** (`return / pickup`) y tasa de conversión.

---

## 2. Cómo se detecta un "alcance" sin cámaras nuevas ni pose

Es la decisión de diseño central del módulo, y conviene poder defenderla en la
sustentación.

El módulo 3 hoy entrega solo bounding boxes. Cuando una persona estira el brazo
hacia el estante, **su silueta se ensancha sin que cambie su altura**. Por eso
la señal que usamos es la relación de aspecto `ancho / alto` del bbox, no el
ancho crudo: si la persona se aleja de la cámara, ancho y alto se reducen
juntos y el aspecto no se mueve. Esa invarianza a la escala está cubierta por
un test (`test_es_invariante_a_la_escala`).

Cada `track_id` tiene su **propia línea base** (mediana móvil de sus frames en
reposo), así que no importa si la persona es más ancha, lleva mochila o está de
perfil: se compara contra sí misma, no contra un promedio poblacional.

Sobre esa señal:

- **Histéresis**: el alcance empieza en +18% sobre la línea base y termina al
  bajar de +8%. Sin esto, un gesto sostenido generaría un evento por frame.
- **Validación de duración**: menos de 300 ms es ruido del detector; más de
  8 s casi siempre es que dos bboxes se fusionaron.
- **Confianza** por evento (0-1), combinando qué tan marcado fue el gesto y
  cuántos frames lo sostuvieron. Se puede filtrar con `--min-confianza`.

Si más adelante el módulo 2/3 entrega `keypoints` (YOLOv8-pose, como sugiere el
stack del reto), se cambia a `--modo-alcance pose` y se usa la extensión real
muñeca-hombro normalizada por el torso. **La máquina de estados no cambia**: el
detector está detrás de una interfaz común. Ese camino ya está implementado y
probado (`test_detector_pose_usa_keypoints`), a la espera de los keypoints.

---

## 3. El supuesto que hay que declarar

**No reconocemos el producto.** Un alcance no dice si la mano volvió llena o
vacía. La regla que usamos es de secuencia, no de visión:

- el **primer** alcance de un episodio se interpreta como pick-up;
- un alcance **posterior en la misma zona y el mismo episodio** se interpreta
  como put-back;
- si la persona se va estando en `CON_PRODUCTO`, el pick-up se cuenta como
  convertido (`takeaway`).

Es la convención de los estudios de observación manual en retail, y es lo que
permite calcular la tasa de rechazo. Sus límites conocidos: alguien que toma
dos productos seguidos se registra como toma + devolución, y alguien que solo
acomoda el estante se registra como interacción. Un clasificador de "mano
llena / mano vacía" corregiría ambos casos y solo cambiaría la interpretación
en `_procesar_alcance`, no la estructura.

---

## 4. Robustez frente al tracking real

ByteTrack pierde el ID por oclusión durante uno o dos frames. Si cerráramos el
episodio de inmediato, una sola visita se partiría en varias y los conteos se
inflarían. Por eso la salida de una zona solo se confirma tras
`--gracia-frames` frames sin ver a la persona (default: 5, o sea medio segundo
a 10 fps). Cubierto por `test_oclusion_corta_no_fragmenta_el_episodio`.

Esto también explica por qué este módulo **calcula su propia permanencia** en
lugar de depender del `dwell_time.jsonl` del módulo 5: ese módulo no tiene
ventana de gracia y fragmenta los episodios cuando el tracker parpadea. El
archivo de Diego se usa para **enriquecer y contrastar**, no como fuente
primaria: cada evento canónico lleva `dwell_modulo5_s` y `detuvo_modulo5`
cuando hay cruce, y el `reporte_integracion.json` dice cuántos eventos
cruzaron. Si esa cifra baja, algo se desalineó entre los dos módulos.

---

## 5. Doble salida: canónica y de cumplimiento

El validador del módulo 8 (Paula) acepta **solo siete campos**
(`track_id`, `zone_id`, `product_id`, `event_type`, `dwell_time_s`,
`timestamp`, `bbox`) y **cuatro tipos de evento** (`approach`, `pickup`,
`return`, `pass_by`). Cualquier campo extra marca el registro como no conforme,
y `timestamp` debe ser ISO 8601, no milisegundos relativos.

Por eso el módulo escribe dos archivos:

| Archivo | Para quién | Contenido |
|---|---|---|
| `eventos_interaccion.jsonl` | módulos 6 y 7 (pipeline, dashboard) | formato canónico completo: confianza, `episodio_id`, detalle del alcance, cruce con el módulo 5 |
| `eventos_compliance.jsonl` | módulo 8 (validador) | proyección mínima con los 7 campos permitidos |

Verificado corriendo el validador real de Paula sobre la salida:
**59/59 registros conformes**.

Dos decisiones deliberadas en la proyección:

- `takeaway` **no se exporta**: no está en el catálogo acordado. La conversión
  sigue siendo derivable (es un `pickup` sin `return` posterior en el mismo
  episodio) y aparece completa en el archivo canónico y en las métricas.
- `bbox` **no se exporta** aunque está permitido: no aporta a ninguna métrica y
  es el único campo del esquema que aproxima la posición corporal.
  Minimización de datos, artículo 4 literal (c) de la Ley 1581 de 2012.

---

## 6. Instalación

```bash
# No hay nada que instalar: solo biblioteca estándar de Python 3.10+
python3 --version
```

El módulo **no usa NumPy, OpenCV ni Ultralytics** a propósito. El
point-in-polygon está implementado con ray casting en Python puro. Eso apoya
directamente el criterio de "viabilidad edge" del reto: esta capa corre en
cualquier dispositivo con Python, sin dependencias binarias.

---

## 7. Ejecución

### Pipeline completo

```bash
# 1. Eventos a partir del tracking real
python deteccion_eventos/src/run_events.py \
    --tracking tracking/output/tracking.jsonl \
    --zonas mapas_de_calor/config/zonas.json \
    --dwell tiempo_permanencia/output/dwell_time.jsonl \
    --productos pipeline/config/productos.json \
    --outdir deteccion_eventos/output

# 2. Verificar que la salida pasa el validador del módulo 8
python deteccion_eventos/tools/verificar_cumplimiento.py \
    --eventos deteccion_eventos/output/eventos_compliance.jsonl \
    --validador validador_recomendador_v3.py
```

### Sin esperar al módulo 3

```bash
# Genera tracking sintético + ground truth
python deteccion_eventos/tools/simular_tracking.py \
    --zonas mapas_de_calor/config/zonas.json \
    --output deteccion_eventos/output/tracking_sintetico.jsonl \
    --personas 40 --seed 7

python deteccion_eventos/src/run_events.py \
    --tracking deteccion_eventos/output/tracking_sintetico.jsonl \
    --zonas mapas_de_calor/config/zonas.json \
    --outdir deteccion_eventos/output

# Exactitud contra el ground truth
python deteccion_eventos/tools/evaluar_exactitud.py \
    --eventos deteccion_eventos/output/eventos_interaccion.jsonl \
    --ground-truth deteccion_eventos/output/tracking_sintetico_ground_truth.json
```

### Parámetros

| Parámetro | Default | Descripción |
|---|---|---|
| `--tracking` | — | `tracking.jsonl` del módulo 3 |
| `--zonas` | — | `zonas.json` del módulo 4 (fuente única) |
| `--dwell` | — | `dwell_time.jsonl` del módulo 5 (opcional) |
| `--productos` | — | mapa `zone_id → SKU`, en `pipeline/config/productos.json` (opcional) |
| `--min-dwell` | `2.0` | segundos para considerar que se detuvo (igual al módulo 5) |
| `--gracia-frames` | `5` | frames que puede desaparecer un track sin cerrar el episodio |
| `--modo-alcance` | `geometrico` | `geometrico` \| `pose` |
| `--umbral-entrada` | `0.18` | expansión relativa que inicia un alcance |
| `--umbral-salida` | `0.08` | expansión bajo la cual termina (histéresis) |
| `--min-confianza` | `0.0` | descarta alcances débiles |
| `--t0` | `2026-08-20T09:00:00` | hora real de inicio del video, para el `timestamp` ISO |

---

## 8. Salidas

### `output/eventos_interaccion.jsonl` (canónico)

```json
{"track_id": "12", "zone_id": "gondola_A3", "event_type": "pickup", "timestamp_ms": 4500.0, "dwell_time_s": 3.8, "confianza": 0.96, "episodio_id": "12-gondola_A3-1", "detalle": {"duracion_alcance_ms": 900.0, "expansion_pico": 0.42, "frames_alcance": 10, "detector": "geometrico"}, "dwell_modulo5_s": 5.0, "detuvo_modulo5": true}
```

### `output/eventos_compliance.jsonl` (módulo 8)

```json
{"track_id": "12", "zone_id": "gondola_A3", "event_type": "pickup", "dwell_time_s": 3.8, "timestamp": "2026-08-20T09:00:04", "product_id": "SKU_1003_lacteos"}
```

### `output/metricas_interaccion.json` (dashboard)

```json
{
  "zone_id": "gondola_A1",
  "personas_unicas": 5,
  "embudo": {"visitas": 5, "pasa_de_largo": 1, "se_detiene": 4,
             "toma_producto": 4, "devuelve": 2, "se_lo_lleva": 2},
  "tasa_detencion": 0.8, "tasa_interaccion": 1.0,
  "tasa_rechazo": 0.5, "tasa_conversion": 0.5,
  "dwell_promedio_s": 3.48, "temperatura": "caliente"
}
```

Incluye además `alertas`: señales accionables (`zona_fria`, `rechazo_alto`,
`trafico_sin_parada`) para el motor de recomendación, que es un entregable
aparte.

### `output/reporte_integracion.json`

Diagnóstico para las reuniones de equipo: eventos por tipo, alcances
descartados y con qué motivo, y cuántos eventos cruzaron con el módulo 5.

---

## 9. Tests y exactitud

```bash
python deteccion_eventos/tests/test_interaction_events.py
# Ran 48 tests — OK
```

Sobre 40 personas sintéticas (667 frames a 10 fps, con oclusiones simuladas):

| Evento | Esperados | Detectados | Precisión | Recall | F1 |
|---|---|---|---|---|---|
| approach | 20 | 20 | 1.00 | 1.00 | 1.00 |
| pass_by | 13 | 13 | 1.00 | 1.00 | 1.00 |
| pickup | 17 | 17 | 1.00 | 1.00 | 1.00 |
| return | 9 | 9 | 1.00 | 1.00 | 1.00 |
| takeaway | 8 | 8 | 1.00 | 1.00 | 1.00 |

**Hay que leer esta tabla con honestidad y decirlo así en la sustentación:** el
simulador genera exactamente la señal que el detector busca, así que un F1 de
1.00 demuestra que la máquina de estados es correcta, **no** que el módulo
tenga esa exactitud sobre video real. Es una prueba de corrección, no una
medición de desempeño en campo.

Lo que sí dice algo del comportamiento real es el barrido de sensibilidad
(`--factor-alcance` controla qué tanto ensancha el brazo la silueta):

| Ensanchamiento del gesto | Recall de `pickup` | Precisión |
|---|---|---|
| +30% | 1.00 | 1.00 |
| +20% | 1.00 | 1.00 |
| +15% | 0.00 | — |
| +10% | 0.00 | — |

Con el umbral por defecto el detector necesita un gesto que ensanche la
silueta al menos ~20%. El dato importante es **cómo falla**: por debajo de ese
punto no aparecen falsos positivos, solo omisiones. El módulo prefiere no
reportar una interacción antes que inventarla, que es lo correcto cuando el
tablero se va a usar para mover producto en la tienda. Si en el video real los
gestos quedan por debajo, se baja `--umbral-entrada` o se pasa a `--modo-alcance
pose`.

---

## 10. Privacidad por diseño (Ley 1581 de 2012)

- El módulo consume únicamente números: bboxes, timestamps e IDs opacos de
  ByteTrack. No recibe ni almacena imágenes.
- No se calcula ni se guarda ningún dato biométrico. No hay rostro, no hay
  embedding, no hay estimación de edad, género ni emoción.
- El estado de una persona se **borra** apenas termina su episodio
  (`detector.olvidar()`), cubierto por `test_estado_se_libera_al_cerrar_episodio`.
  El track deja de existir en memoria cuando deja de ser útil.
- El archivo de cumplimiento aplica minimización: no exporta `bbox` aunque el
  esquema lo permita.
- El `track_id` se trata como opaco: no se cruza con ninguna otra fuente de
  datos. Un ID de ByteTrack identifica un track dentro de la secuencia visible,
  no a una persona.
- El cumplimiento se **verifica automáticamente** con el validador del módulo 8
  (`tools/verificar_cumplimiento.py`), no se declara por escrito nada más.

---

## 11. Estructura

```text
deteccion_eventos/
├── README.md
├── requirements.txt
├── src/
│   ├── zonas.py                  carga de zonas + geometría (sin dependencias)
│   ├── reach_detector.py         detección de alcance (geométrico / pose)
│   ├── state_machine.py          máquina de estados por persona
│   ├── metrics.py                embudo, tasas, alertas, cruce con módulo 5
│   └── run_events.py             CLI
├── tools/
│   ├── simular_tracking.py       tracking sintético + ground truth
│   ├── evaluar_exactitud.py      precisión / recall / F1 por tipo de evento
│   └── verificar_cumplimiento.py corre el validador del módulo 8
└── tests/
    └── test_interaction_events.py  48 tests
```
