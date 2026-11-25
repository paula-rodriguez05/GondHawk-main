# GondHawk — Góndola Inteligente

Prototipo de visión computacional que convierte video de una superficie
comercial en métricas accionables de *space management*, operando bajo
privacidad por diseño: sin reconocimiento facial, sin datos biométricos y sin
enviar nada a la nube.

**Reto 1 — HackTech 5.0 2026** · Empresa proponente: Scapder · Equipo: Ship Club

---

## El problema

Los retailers deciden cómo distribuir el espacio —el recurso más caro de la
tienda— con datos de punto de venta. El POS dice **qué se vendió**, pero no
**por qué**: no revela qué miró el cliente, qué tomó y devolvió, ni por dónde
circuló. Al mismo tiempo, casi todas las tiendas ya tienen cámaras que solo
graban, sin gestionar nada.

GondHawk transforma ese video pasivo en el **embudo físico de compra**:

```
pasa por la zona → se detiene → toma producto → devuelve / se lo lleva
```

---

## Qué hace

- **Detección y seguimiento anónimo** de personas, con trayectorias por zona.
- **Mapa de calor de flujo** calculado sobre el tránsito real del video.
- **Tiempo de permanencia** (dwell) frente a cada góndola.
- **Eventos de interacción**: aproximación, toma de producto (pick-up) y
  devolución al estante (put-back), mediante una máquina de estados por persona.
- **Métricas de space management**: zonas frías y calientes, tasa de
  interacción, tasa de rechazo (put-back / pick-up) y tasa de conversión.
- **Recomendaciones** de reubicación y ajuste de planograma.
- **Detección automática de zonas** a partir del video, distinguiendo góndola,
  pasillo y caja de pago.
- **Anonimización** de rostros en todo material visual generado.
- **Verificación de escena**: rechaza videos que no son de superficie comercial.
- **Reportes descargables** en PDF, Excel y Word.
- **Historial** de todos los análisis realizados.

---

## Arquitectura

```
video → detección → tracking → zonas → permanencia → eventos → métricas → tablero
         (mód. 2)   (mód. 3)  (mód. 4)  (mód. 5)    (mód. 1)   (mód. 6)   (mód. 7)
                                                                              ↑
                                                        validación (mód. 8) ──┘
```

| Módulo | Responsable | Qué hace |
|---|---|---|
| 2 — Detección de personas | Samuel | YOLOv8 sobre cada frame |
| 3 — Tracking | Juan | ByteTrack, asigna IDs anónimos |
| 4 — Mapas de calor | Arturo | Densidad de tránsito y zonas |
| 5 — Tiempo de permanencia | Diego | Dwell time por zona |
| 1 — Eventos de interacción | Nicol | Máquina de estados: approach, pickup, return |
| 6 — Pipeline | Laura | Orquesta todo, API y reportes |
| 8 — Cumplimiento | Paula | Valida privacidad por diseño |
| 7 — Frontend | Julian | Tablero React |

### Estructura

```
GondHawk/
├── backend/
│   ├── api_server.py                  API FastAPI
│   ├── deteccion_personas/            módulo 2
│   ├── tracking/                      módulo 3
│   ├── mapas_de_calor/                módulo 4
│   ├── tiempo_permanencia/            módulo 5
│   ├── deteccion_eventos/             módulo 1
│   ├── pipeline/
│   │   ├── src/
│   │   │   ├── pipeline.py            orquestador
│   │   │   ├── preproceso.py          escalado de zonas, blur, verificación
│   │   │   ├── zonas_auto.py          propuesta automática de zonas
│   │   │   ├── video_anotado.py       render del video con detección
│   │   │   ├── historial.py           historial de análisis
│   │   │   ├── reportes.py            PDF / Excel / Word
│   │   │   └── recomendador.py        motor de recomendaciones
│   │   └── config/productos.json      mapa zone_id → SKU
│   └── validador_recomendador_v3.py   módulo 8
└── frontend/                          tablero React + Vite
```

---

## Instalación

### Requisitos

- Python 3.10 o superior
- Node.js 18 o superior

### Backend

```bash
cd backend
python -m venv .venv

# Windows
.venv\Scripts\Activate.ps1
# Linux / macOS
source .venv/bin/activate

pip install -r pipeline/requirements.txt
pip install reportlab openpyxl python-docx     # reportes descargables
```

Video de prueba:

```bash
python deteccion_personas/data/descargar_video_prueba.py
```

### Frontend

```bash
cd frontend
npm install
```

---

## Uso

### Interfaz web

Dos terminales:

```bash
# Terminal 1 — backend
cd backend
python api_server.py    

# Para recargar los errores:
uvicorn api_server:app --reload

# Terminal 2 — frontend
cd frontend
npm run dev
```

Abre `http://localhost:5173`, selecciona un video y analiza. Deja activada la
casilla **"Detectar zonas automáticamente"**.

### Línea de comandos

```bash
python pipeline/src/pipeline.py \
    --video ruta/al/video.mp4 \
    --outdir pipeline/output \
    --zonas-auto
```

Parámetros útiles:

| Parámetro | Default | Qué hace |
|---|---|---|
| `--zonas-auto` | apagado | Propone zonas a partir del video |
| `--frame-skip N` | 1 | Procesa 1 de cada N frames |
| `--modo-anonimizacion` | blur | `blur`, `pixelado` o `solido` |
| `--sin-verificar-escena` | — | Omite la verificación de superficie comercial |
| `--umbral-escena` | 0.45 | Puntaje mínimo para aceptar el video |
| `--min-dwell` | 2.0 | Segundos para considerar que alguien se detuvo |
| `--sin-video-anotado` | — | No genera el video con detección |

### Salidas

En `pipeline/output/`:

| Archivo | Contenido |
|---|---|
| `metricas_interaccion.json` | Embudo por góndola, tasas y alertas |
| `eventos_interaccion.jsonl` | Eventos con detalle completo |
| `eventos_compliance.jsonl` | Proyección que pasa el validador del módulo 8 |
| `heatmap.png` | Mapa de calor sobre el frame real |
| `video_anotado.mp4` | Video con detección, tracking y rostros difuminados |
| `zonas_propuestas.png` | Zonas detectadas, para revisión visual |

---

## API

| Método | Endpoint | Qué hace |
|---|---|---|
| `POST` | `/api/videos/analyze?zonas_auto=true&frame_skip=1` | Analiza un video |
| `GET` | `/api/analisis` | Lista el historial |
| `GET` | `/api/analisis/{id}` | Detalle de un análisis |
| `GET` | `/api/analisis/{id}/archivo/{nombre}` | Heatmap, video, JSON |
| `GET` | `/api/analisis/{id}/reporte/{pdf\|excel\|word}` | Descarga el reporte |
| `GET` | `/api/analisis/{id}/recomendaciones` | Recomendaciones |
| `DELETE` | `/api/analisis/{id}` | Elimina un análisis |

Documentación interactiva en `http://localhost:8000/docs`.

---

## Privacidad por diseño

El reto premia explícitamente las soluciones que respetan la **Ley 1581 de
2012**, con el dato biométrico excluido por diseño. GondHawk lo cumple así:

- **Sin reconocimiento facial.** La anonimización difumina la región de cabeza
  a partir del bbox de la persona. No usa un detector de rostros a propósito:
  localizar una cara es computar el dato biométrico que el reto excluye.
- **Sin almacenamiento de imágenes de personas.** El único material visual que
  sale del sistema —heatmap y video anotado— tiene los rostros difuminados
  antes de guardarse.
- **Identificadores temporales.** Los `track_id` son opacos, viven dentro de la
  secuencia y se borran al terminar el episodio.
- **Minimización.** El archivo de cumplimiento no exporta `bbox` aunque el
  esquema lo permita.
- **Procesamiento local.** Ningún dato sale del equipo.
- **Verificación automática.** El cumplimiento no se declara, se comprueba:

```bash
python deteccion_eventos/tools/verificar_cumplimiento.py \
    --eventos pipeline/output/eventos_compliance.jsonl \
    --validador validador_recomendador_v3.py
```

---

## Rendimiento

Medido sobre un portátil sin GPU, video de 3.753 frames a 640×360:

| Configuración | fps efectivos | Tiempo |
|---|---|---|
| Todos los frames | 26 | 142 s |
| 1 de cada 3 | 82 | 45 s |

La capa de eventos de interacción no usa NumPy ni OpenCV: corre con biblioteca
estándar de Python, lo que apoya la viabilidad edge del prototipo.

**Advertencia sobre `--frame-skip`:** acelera el análisis pero le da al tracker
menos información para asociar identidades entre frames, y eso fragmenta los
episodios de permanencia. Para métricas confiables, usar `--frame-skip 1`.

---

## Pruebas

```bash
python deteccion_eventos/tests/test_interaction_events.py   # 48 tests
python tiempo_permanencia/test_dwell_time.py                # 15 tests
python pipeline/tests/test_pipeline.py
```

---

## Limitaciones conocidas

Se documentan porque afectan cómo deben leerse las métricas:

1. **No se reconoce el producto.** Un alcance no dice si la mano volvió llena o
   vacía. La regla es de secuencia: el primer alcance de una visita se
   interpreta como pick-up y el siguiente como put-back. Alguien que toma dos
   productos seguidos se registra como toma + devolución.

2. **Persistencia del tracking.** El tracker pierde y reasigna identidades con
   frecuencia. Cuando una visita se fragmenta en episodios cortos, ninguno
   alcanza el umbral de permanencia y el embudo subestima las interacciones.

3. **Las zonas automáticas son una propuesta.** Se generan combinando
   estructura visual y tránsito, y deben revisarse con
   `mapas_de_calor/src/zone_definer.py` antes de presentar métricas. Un layout
   mal definido produce cifras que parecen válidas y no lo son.

4. **La verificación de escena es heurística**, no un clasificador entrenado.
   Distingue una tienda de un exterior; no reemplaza el criterio humano.

5. **Un video por análisis.** No hay serie histórica, así que no se calculan
   comparativos entre períodos.

---

## Equipo

Proyecto desarrollado para HackTech 5.0 2026 · Universidad Santo Tomás,
Seccional Tunja.
