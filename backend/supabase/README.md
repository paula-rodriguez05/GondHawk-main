# Persistencia en Supabase

## Qué resuelve

Hasta ahora el historial vivía en `pipeline/output/indice.json` y en carpetas
del disco del servidor. Eso funciona con una sola máquina y se rompe apenas
quieres escalar:

- Dos instancias de la API no comparten historial: cada una ve solo lo suyo.
- Si el contenedor se recicla, se pierde todo.
- No se puede preguntar nada entre análisis. "Cómo se comportó la góndola 3
  este mes" obliga a abrir y sumar treinta archivos a mano.

Con Supabase, las métricas y los eventos quedan en Postgres (consultables con
SQL) y los binarios en Storage. El disco pasa a ser solo una caché.

## Reparto de responsabilidades

| Dato | Dónde vive | Por qué |
|---|---|---|
| KPIs del análisis, métricas por zona, eventos | Postgres | Es lo que se consulta, ordena y agrega |
| Video anotado, heatmap, PNG de zonas, `.jsonl` | Storage (bucket `gondhawk`, privado) | Un mp4 en una columna hace lenta toda consulta que ni lo toca |
| Copia local de los archivos | Disco | Caché: evita descargar el video en cada reproducción |

## Puesta en marcha

1. **Crear el proyecto** en supabase.com. Elige la región más cercana
   (`South America (São Paulo)` para Colombia).

2. **Ejecutar el esquema.** Abre el SQL Editor, pega el contenido completo de
   `schema.sql` y ejecútalo. Crea las tablas, los índices, las dos vistas de
   agregación y el bucket privado. Es idempotente: puedes volver a correrlo.

3. **Configurar las credenciales.** En Project Settings → API copia la URL del
   proyecto y la **service role key**. Luego:

   ```bash
   cp backend/.env.example backend/.env
   # editar backend/.env con los valores reales
   ```

   La service role key salta el RLS. Va solo en el backend, nunca en el
   frontend ni en el repositorio. Ya está en `.gitignore`; si se te filtra,
   rótala desde el panel.

4. **Instalar la dependencia:**

   ```bash
   pip install -r backend/requirements.txt
   ```

5. **Levantar la API.** Al arrancar verás una de estas dos líneas, que te dice
   contra qué está persistiendo:

   ```
   [almacen] Persistencia en Supabase activa.
   [almacen] Sin credenciales de Supabase: se usa el historial en disco.
   ```

Sin `.env` el sistema funciona igual que antes, contra el disco. Es
deliberado: la demo del hackathon no puede depender de tener internet.

## Qué se agregó al código

- `pipeline/src/almacen.py` — `HistorialSupabase` extiende `HistorialAnalisis`
  y respeta su mismo contrato, así que la API no cambió de forma. Escribe
  primero en disco y después sincroniza: si Supabase falla, el análisis no se
  pierde y el usuario igual recibe su respuesta.
- `api_server.py` — usa `crear_historial()`, que elige el almacén según el
  entorno, y expone `GET /api/analitica/zonas`.

## El endpoint que justifica todo esto

```
GET /api/analitica/zonas?limite=20
```

Devuelve el rendimiento histórico de cada góndola agregado sobre todos los
análisis: visitas totales, tomas totales y tasa de interacción promedio. Con
el historial en disco esta consulta no era viable; aquí la resuelve la vista
`v_rendimiento_zona` en Postgres.

## Consultas útiles para la sustentación

```sql
-- Góndolas con peor conversión (mucha visita, poca toma)
select zone_id, visitas_totales, tomas_totales, tasa_interaccion_promedio
from v_rendimiento_zona
where visitas_totales > 20
order by tasa_interaccion_promedio asc
limit 10;

-- Evolución diaria de la interacción
select date_trunc('day', fecha) as dia,
       count(*) as analisis,
       round(avg(tasa_interaccion), 3) as tasa
from analisis
group by dia
order by dia desc;

-- Distribución de eventos por tipo
select event_type, count(*)
from eventos
group by event_type
order by 2 desc;
```

## Antes de producción

- **Particionar `eventos`** por fecha cuando pase de unos pocos millones de
  filas. Hoy con un índice por `analisis_id` va sobrado.
- **Retención.** Los mp4 son lo que llena el bucket. Vale la pena una tarea
  que borre videos anotados de más de N días conservando las métricas, que es
  lo que de verdad importa a largo plazo.
- **URLs firmadas.** Ahora los archivos se sirven a través de la API, que los
  descarga de Storage. Para muchos usuarios concurrentes conviene que la API
  devuelva una URL firmada y el navegador descargue directo del bucket, sin
  pasar el video por el servidor.
- **RLS por tienda.** Las tablas tienen el RLS activo y sin políticas: solo la
  service role entra. Cuando haya usuarios por tienda, las políticas van sobre
  `analisis.tienda_id`.
