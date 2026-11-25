export const API_BASE = 'http://localhost:8000';

// Opciones de análisis. `zonasAuto` en true por defecto: las zonas guardadas
// corresponden al video con el que se calibró el sistema, así que sobre
// cualquier otro video caen donde no hay góndolas y todas las métricas dan
// cero. Proponerlas a partir del video que se sube es lo correcto por defecto.
export const ANALYSIS_DEFAULTS = {
  zonasAuto: true,
  frameSkip: 1,
};

export const DATA_SOURCES = {
  apiBase: API_BASE,
  analyzeVideo: `${API_BASE}/api/videos/analyze`,
  analyzeVideosBatch: `${API_BASE}/api/videos/analyze-batch`,
  sparkMetricas: `${API_BASE}/api/spark/metricas`,
  heatmapImage: `${API_BASE}/api/videos/heatmap`,
  historial: `${API_BASE}/api/analisis`,
  analisis: (id) => `${API_BASE}/api/analisis/${id}`,
  archivo: (id, nombre) => `${API_BASE}/api/analisis/${id}/archivo/${nombre}`,
  reporte: (id, formato) => `${API_BASE}/api/analisis/${id}/reporte/${formato}`,
  recomendaciones: (id) => `${API_BASE}/api/analisis/${id}/recomendaciones`,
};

export function buildAnalyzeUrl({ zonasAuto, frameSkip } = ANALYSIS_DEFAULTS) {
  const params = new URLSearchParams({
    zonas_auto: String(Boolean(zonasAuto)),
    frame_skip: String(frameSkip ?? 1),
  });
  return `${DATA_SOURCES.analyzeVideo}?${params.toString()}`;
}
