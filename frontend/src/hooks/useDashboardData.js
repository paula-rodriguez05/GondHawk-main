import { useRef, useState } from 'react';
import { DATA_SOURCES } from '../config/dataConfig';

const EMPTY_DATA = {
  zonasGondola: [],
  totalGlobal: { visitas: 0, tasa_interaccion: 0, tasa_rechazo: 0 },
  alertas: [],
  recomendaciones: [],
  recomendacionesFuente: null,
  resumenPipeline: {},
  conteoZonas: [],
  heatmapUrl: null,
  videoAnotadoUrl: null,
  zonasPropuestasUrl: null,
  zonasPropuestas: null,
  tracking: [],
  analisisId: null,
  reportes: null,
  mensaje: null,
};

function absoluta(ruta, cacheKey) {
  if (!ruta) return null;
  const base = ruta.startsWith('http') ? ruta : `${DATA_SOURCES.apiBase}${ruta}`;
  return cacheKey ? `${base}?analysis=${cacheKey}` : base;
}

export function normalizeAnalysisResponse(payload, cacheKey = '') {
  const interaction = payload?.interaction ?? payload ?? {};
  const pipeline = payload?.pipeline ?? {};
  const conteo = payload?.conteo_zonas ?? { zonas: [] };
  const analisisId = payload?.analisis_id ?? null;

  // Los archivos SIEMPRE se sirven desde la carpeta del análisis. El campo
  // heatmap_url quedó guardado apuntando a /api/videos/heatmap, que devuelve
  // el último heatmap generado: al abrir un análisis del historial se veía la
  // imagen del análisis más reciente.
  const archivo = (nombre) =>
    analisisId ? absoluta(`/api/analisis/${analisisId}/archivo/${nombre}`, cacheKey) : null;

  return {
    zonasGondola: Array.isArray(interaction.zonas) ? interaction.zonas : [],
    totalGlobal: interaction.total ?? { visitas: 0, tasa_interaccion: 0, tasa_rechazo: 0 },
    alertas: Array.isArray(interaction.alertas) ? interaction.alertas : [],

    // El pipeline ya deja las recomendaciones dentro de las métricas, así que
    // no hace falta pedirlas por separado; el endpoint queda como respaldo
    // para análisis guardados antes de ese cambio.
    recomendaciones: Array.isArray(interaction.recomendaciones)
      ? interaction.recomendaciones
      : Array.isArray(payload?.recomendaciones)
        ? payload.recomendaciones
        : [],
    recomendacionesFuente: interaction.recomendaciones_fuente ?? null,

    resumenPipeline: pipeline,
    conteoZonas: Array.isArray(conteo.zonas) ? conteo.zonas : [],
    heatmapUrl: archivo('heatmap.png') ?? absoluta(payload?.heatmap_url, cacheKey),
    videoAnotadoUrl: archivo('video_anotado.mp4') ?? absoluta(payload?.video_anotado_url, cacheKey),
    zonasPropuestasUrl: archivo('zonas_propuestas.png'),
    // El poligono de cada zona (para dibujar el Mapa de tienda) y el
    // tracking por frame (para las trayectorias en vivo) solo existen como
    // archivos aparte; se cargan de forma asincrona en updateFromAnalysis.
    zonasPropuestasJsonUrl: archivo('zonas_propuestas.json'),
    // Respaldo para los analisis hechos con zonas fijas, donde el pipeline no
    // genera una propuesta pero si deja las zonas efectivamente usadas.
    zonasUsadasJsonUrl: archivo('zonas_usadas.json'),
    trackingUrl: archivo('tracking.jsonl'),
    zonasPropuestas: null,
    tracking: [],
    analisisId,
    reportes: payload?.reportes ?? null,
    mensaje: payload?.mensaje ?? null,
  };
}

function parseJsonl(texto) {
  return texto
    .split('\n')
    .map((linea) => linea.trim())
    .filter(Boolean)
    .map((linea) => JSON.parse(linea));
}

export function useDashboardData() {
  const [data, setData] = useState(EMPTY_DATA);
  // Cada llamada a updateFromAnalysis/resetData invalida las cargas
  // asincronas (zonas/tracking) de la llamada anterior, para que un fetch
  // lento no repueble el estado despues de "Limpiar" o de analizar otro video.
  const generacionRef = useRef(0);

  function updateFromAnalysis(payload, cacheKey) {
    const generacion = ++generacionRef.current;
    const normalizado = normalizeAnalysisResponse(payload, cacheKey);
    setData(normalizado);

    const fuentesZonas = [
      normalizado.zonasPropuestasJsonUrl,
      normalizado.zonasUsadasJsonUrl,
    ].filter(Boolean);

    (async () => {
      for (const url of fuentesZonas) {
        try {
          const res = await fetch(url);
          if (!res.ok) continue;
          const zonasPropuestas = await res.json();
          if (zonasPropuestas?.zonas?.length) {
            if (generacionRef.current !== generacion) return;
            setData((prev) => ({ ...prev, zonasPropuestas }));
            return;
          }
        } catch {
          // se intenta la siguiente fuente
        }
      }
    })();

    if (normalizado.trackingUrl) {
      fetch(normalizado.trackingUrl)
        .then((res) => (res.ok ? res.text() : null))
        .then((texto) => {
          if (!texto) return;
          if (generacionRef.current !== generacion) return;
          setData((prev) => ({ ...prev, tracking: parseJsonl(texto) }));
        })
        .catch(() => {});
    }
  }

  function resetData() {
    generacionRef.current += 1;
    setData(EMPTY_DATA);
  }

  return { data, updateFromAnalysis, resetData };
}
