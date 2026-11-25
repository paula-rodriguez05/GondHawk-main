-- ═══════════════════════════════════════════════════════════════════════════
-- GondHawk — Esquema de persistencia en Supabase
--
-- Ejecutar completo en el SQL Editor del proyecto de Supabase.
-- Es idempotente: se puede volver a correr sin romper nada.
--
-- Criterio de diseño: a la base va lo que se CONSULTA y se AGREGA (métricas,
-- eventos, zonas). Los binarios (video anotado, heatmap, PNG de zonas) van a
-- Storage, porque meter un mp4 en una columna hace lenta cualquier consulta
-- que ni siquiera lo toque.
-- ═══════════════════════════════════════════════════════════════════════════

create extension if not exists "pgcrypto";

-- ── Tiendas y cámaras ──────────────────────────────────────────────────────
-- El modelo tiene que escalar a varias tiendas y varias cámaras por tienda.
-- Sin esto, todos los análisis quedan en un mismo saco y no se puede comparar
-- una góndola de una sede contra la misma góndola de otra.

create table if not exists public.tiendas (
  id          uuid primary key default gen_random_uuid(),
  nombre      text not null,
  ciudad      text,
  creado_en   timestamptz not null default now()
);

create table if not exists public.camaras (
  id          uuid primary key default gen_random_uuid(),
  tienda_id   uuid references public.tiendas(id) on delete cascade,
  nombre      text not null,
  -- Resolución nativa: sin ella no se pueden reescalar los polígonos de zonas
  -- entre videos de distinta calidad de la misma cámara.
  frame_width  integer,
  frame_height integer,
  creado_en   timestamptz not null default now()
);

-- ── Análisis ───────────────────────────────────────────────────────────────
-- Una fila por corrida del pipeline. El id es el mismo string que ya usa el
-- historial en disco ("20260908T101500_video"), para no romper las URLs
-- existentes de /api/analisis/{id}/archivo/{nombre}.

create table if not exists public.analisis (
  id            text primary key,
  tienda_id     uuid references public.tiendas(id) on delete set null,
  camara_id     uuid references public.camaras(id) on delete set null,
  fecha         timestamptz not null default now(),
  video         text not null,
  sintetico     boolean not null default false,

  -- KPIs aplanados: son los que pinta la lista del historial. Estar en
  -- columnas y no dentro del jsonb es lo que permite ordenar y filtrar sin
  -- abrir el detalle completo de cada corrida.
  personas             integer,
  frames               integer,
  duracion_analisis_s  numeric,
  visitas              integer,
  se_detiene           integer,
  toma_producto        integer,
  devuelve             integer,
  tasa_interaccion     numeric,
  tasa_rechazo         numeric,

  -- Payload completo, por si se agrega un KPI nuevo y hay que recalcular
  -- histórico sin volver a procesar los videos.
  detalle       jsonb not null default '{}'::jsonb,
  archivos      jsonb not null default '{}'::jsonb,
  creado_en     timestamptz not null default now()
);

create index if not exists idx_analisis_fecha    on public.analisis (fecha desc);
create index if not exists idx_analisis_tienda   on public.analisis (tienda_id, fecha desc);
create index if not exists idx_analisis_sintetico on public.analisis (sintetico);

-- ── Métricas por zona ──────────────────────────────────────────────────────
-- Aquí está el verdadero valor de tener base de datos: poder preguntar
-- "¿cómo se comportó la góndola 3 en los últimos 30 días?" sin abrir 30 JSON.

create table if not exists public.zonas_metricas (
  id                bigserial primary key,
  analisis_id       text not null references public.analisis(id) on delete cascade,
  zone_id           text not null,
  es_gondola        boolean,
  visitas           integer default 0,
  se_detiene        integer default 0,
  toma_producto     integer default 0,
  devuelve          integer default 0,
  tasa_interaccion  numeric,
  tasa_rechazo      numeric,
  visitas_unicas    integer,
  pct_tiempo_ocupada numeric,
  poligono          jsonb,
  unique (analisis_id, zone_id)
);

create index if not exists idx_zonas_analisis on public.zonas_metricas (analisis_id);
create index if not exists idx_zonas_zone     on public.zonas_metricas (zone_id);

-- ── Eventos de interacción ─────────────────────────────────────────────────
-- La tabla que más crece. Un video de 3 min genera cientos de filas; mil
-- videos, cientos de miles. Por eso solo lleva los campos que se consultan y
-- los índices justos.

create table if not exists public.eventos (
  id            bigserial primary key,
  analisis_id   text not null references public.analisis(id) on delete cascade,
  person_id     integer,
  zone_id       text,
  event_type    text not null,
  timestamp_ms  double precision,
  confianza     numeric
);

create index if not exists idx_eventos_analisis on public.eventos (analisis_id);
create index if not exists idx_eventos_tipo     on public.eventos (event_type);
create index if not exists idx_eventos_zona     on public.eventos (zone_id, event_type);

-- ── Vistas de agregación ───────────────────────────────────────────────────
-- Lo que antes calculaba `historial.estadisticas()` recorriendo el índice en
-- memoria. Con la vista, el costo lo paga Postgres y no crece con el número
-- de análisis guardados.

create or replace view public.v_estadisticas_globales as
select
  count(*)                        as total_analisis,
  min(fecha)                      as primer_analisis,
  max(fecha)                      as ultimo_analisis,
  round(avg(tasa_interaccion), 4) as promedio_tasa_interaccion,
  round(avg(tasa_rechazo), 4)     as promedio_tasa_rechazo,
  coalesce(sum(visitas), 0)       as total_visitas
from public.analisis;

-- Rendimiento histórico de cada góndola: la consulta que justifica todo esto.
create or replace view public.v_rendimiento_zona as
select
  z.zone_id,
  a.tienda_id,
  count(distinct z.analisis_id)   as analisis,
  sum(z.visitas)                  as visitas_totales,
  sum(z.toma_producto)            as tomas_totales,
  round(avg(z.tasa_interaccion), 4) as tasa_interaccion_promedio,
  round(avg(z.tasa_rechazo), 4)     as tasa_rechazo_promedio,
  max(a.fecha)                    as ultimo_analisis
from public.zonas_metricas z
join public.analisis a on a.id = z.analisis_id
where z.es_gondola is not false
group by z.zone_id, a.tienda_id;

-- ── Seguridad ──────────────────────────────────────────────────────────────
-- RLS activo y SIN políticas públicas: solo la service_role (la que usa el
-- backend) puede leer y escribir. El frontend nunca habla directo con la base,
-- pasa siempre por la API, así que no hace falta abrir nada más.
-- Si más adelante se agregan usuarios, aquí van las políticas por tienda.

alter table public.tiendas        enable row level security;
alter table public.camaras        enable row level security;
alter table public.analisis       enable row level security;
alter table public.zonas_metricas enable row level security;
alter table public.eventos        enable row level security;

-- ── Storage ────────────────────────────────────────────────────────────────
-- Bucket privado para los artefactos. Se sirve por URLs firmadas de corta
-- duración generadas por el backend; nunca público, porque aunque los rostros
-- van difuminados, un video de tienda no debería quedar accesible por URL.

insert into storage.buckets (id, name, public)
values ('gondhawk', 'gondhawk', false)
on conflict (id) do nothing;
