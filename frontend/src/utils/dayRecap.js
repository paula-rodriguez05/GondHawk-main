function humanZoneName(zoneId) {
  return (zoneId || '').replace(/_/g, ' ');
}

function classifyZone(zoneId, gondolaIds) {
  if (gondolaIds.has(zoneId)) return 'gondola';
  const id = (zoneId || '').toLowerCase();
  if (id.includes('caja') || id.includes('checkout') || id.includes('pago')) return 'caja';
  if (id.includes('pasillo') || id.includes('aisle') || id.includes('corredor')) return 'pasillo';
  return 'otra';
}

// Traduce las métricas ya calculadas (metricas_interaccion.json +
// conteo_zonas.json) a un puñado de frases en lenguaje natural, tipo
// "hoy el 70% del tráfico pasó por el pasillo central, pero solo el 18%
// se detuvo en una góndola". No agrega ningún cálculo nuevo: solo cuenta
// en palabras lo que el dashboard ya muestra en números y tablas.
export function generateDayRecap({ totalGlobal, zonasGondola = [], conteoZonas = [] }) {
  if (!conteoZonas.length && !zonasGondola.length) return [];

  const gondolaIds = new Set(zonasGondola.map((z) => z.zone_id));
  const conteoMap = new Map(conteoZonas.map((z) => [z.zone_id, z]));
  const bullets = [];

  const pasillos = conteoZonas.filter((z) => classifyZone(z.zone_id, gondolaIds) === 'pasillo');
  const topPasillo = [...pasillos].sort(
    (a, b) => (b.pct_tiempo_ocupada || 0) - (a.pct_tiempo_ocupada || 0),
  )[0];

  if (topPasillo && topPasillo.pct_tiempo_ocupada > 0) {
    const tasaInteraccionPct = Math.round((totalGlobal?.tasa_interaccion || 0) * 100);
    bullets.push(
      `El ${Math.round(topPasillo.pct_tiempo_ocupada)}% del tiempo hubo alguien circulando por ` +
        `${humanZoneName(topPasillo.zone_id)}, pero solo el ${tasaInteraccionPct}% de las visitas ` +
        'terminó deteniéndose en una góndola.',
    );
  }

  const gondolasConDatos = zonasGondola.map((z) => ({
    ...z,
    pct_tiempo_ocupada: conteoMap.get(z.zone_id)?.pct_tiempo_ocupada ?? 0,
  }));
  const topGondola = [...gondolasConDatos].sort(
    (a, b) => (b.pct_tiempo_ocupada || 0) - (a.pct_tiempo_ocupada || 0),
  )[0];

  if (topGondola && topGondola.pct_tiempo_ocupada > 0) {
    const conversionPct = Math.round((topGondola.tasa_conversion || 0) * 100);
    bullets.push(
      `${humanZoneName(topGondola.zone_id)} fue la góndola con más movimiento: ocupada el ` +
        `${topGondola.pct_tiempo_ocupada.toFixed(0)}% del tiempo, con ${conversionPct}% de ` +
        'conversión entre quienes tomaron un producto.',
    );
  }

  const zonasMuertas = conteoZonas.filter((z) => (z.visitas_unicas || 0) === 0);
  if (zonasMuertas.length > 0) {
    const nombres = zonasMuertas.map((z) => humanZoneName(z.zone_id)).join(', ');
    const sujeto = zonasMuertas.length === 1 ? 'Una zona no tuvo' : `${zonasMuertas.length} zonas no tuvieron`;
    bullets.push(
      `${sujeto} ninguna visita en todo el video: ${nombres}. Vale la pena revisar si están bien ` +
        'ubicadas o si conviene mover producto ahí.',
    );
  }

  const tomaProducto = totalGlobal?.toma_producto || 0;
  if (tomaProducto > 0) {
    const tasaRechazoPct = Math.round((totalGlobal?.tasa_rechazo || 0) * 100);
    bullets.push(
      tasaRechazoPct > 0
        ? `De las personas que tomaron un producto, el ${tasaRechazoPct}% lo devolvió sin llevárselo.`
        : 'Todas las personas que tomaron un producto se lo llevaron: 0% de devoluciones.',
    );
  }

  return bullets;
}
