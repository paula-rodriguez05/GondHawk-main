import { useState } from 'react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  LabelList,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

const METRICAS = [
  { id: 'flujo', etiqueta: 'Flujo', unidad: 'visitantes', formato: 'entero' },
  { id: 'dwell', etiqueta: 'Dwell', unidad: 'segundos', formato: 'decimal' },
  { id: 'interaccion', etiqueta: 'Interacción', unidad: '%', formato: 'porcentaje' },
  { id: 'rechazo', etiqueta: 'Rechazo', unidad: '%', formato: 'porcentaje' },
  { id: 'comparativa', etiqueta: 'Interacción vs rechazo', unidad: '%', formato: 'doble' },
];

const ESTADOS = {
  caliente: 'Excelente',
  templada: 'Mejorable',
  fria: 'Crítica',
  sin_datos: 'Sin datos',
};

function formatear(valor, formato) {
  if (formato === 'porcentaje') return `${Math.round(valor)}%`;
  if (formato === 'decimal') return `${Number(valor).toFixed(1)} s`;
  return Math.round(valor).toLocaleString('es-CO');
}

function TooltipGondola({ active, payload }) {
  const zona = payload?.[0]?.payload;
  if (!active || !zona) return null;

  return (
    <div className="interaction-chart-tooltip">
      <strong>{zona.zone_id}</strong>
      <span>Flujo: {formatear(zona.flujo, 'entero')} visitantes</span>
      <span>Dwell: {formatear(zona.dwell, 'decimal')}</span>
      <span>Interacción: {formatear(zona.interaccion, 'porcentaje')}</span>
      <span>Rechazo: {formatear(zona.rechazo, 'porcentaje')}</span>
      <span>Estado: {zona.estado}</span>
    </div>
  );
}

export function InteractionRateChart({ zonas, multiprocessingUsed, sparkMetricas }) {
  const [metricaId, setMetricaId] = useState('interaccion');
  const metrica = METRICAS.find((item) => item.id === metricaId) ?? METRICAS[2];
  const datos = zonas.map((zona) => ({
    zone_id: zona.zone_id,
    flujo: zona.embudo?.visitas ?? zona.visitas ?? 0,
    dwell: zona.dwell_promedio_s ?? 0,
    interaccion: Math.round((zona.tasa_interaccion ?? 0) * 100),
    rechazo: Math.round((zona.tasa_rechazo ?? 0) * 100),
    estado: ESTADOS[zona.temperatura] ?? 'Sin datos',
  }));
  const doble = metrica.formato === 'doble';
  const series = doble
    ? [
        { clave: 'interaccion', etiqueta: 'Interacción', color: 'var(--success)' },
        { clave: 'rechazo', etiqueta: 'Rechazo', color: 'var(--danger)' },
      ]
    : [{ clave: metrica.id, etiqueta: metrica.etiqueta, color: 'var(--success)' }];
  const maxDato = Math.max(0, ...datos.flatMap((zona) => series.map((item) => zona[item.clave])));
  const formatoValor = metrica.formato === 'doble' ? 'porcentaje' : metrica.formato;
  const valorEje = (valor) => {
    if (metrica.formato === 'porcentaje' || doble) return `${Math.round(valor)}%`;
    if (metrica.formato === 'decimal') return `${Number(valor).toFixed(1)} s`;
    return Math.round(valor).toLocaleString('es-CO');
  };

  const manejarTeclas = (event) => {
    const indice = METRICAS.findIndex((item) => item.id === metricaId);
    let siguiente;
    if (event.key === 'ArrowRight') siguiente = (indice + 1) % METRICAS.length;
    else if (event.key === 'ArrowLeft') siguiente = (indice - 1 + METRICAS.length) % METRICAS.length;
    else if (event.key === 'Home') siguiente = 0;
    else if (event.key === 'End') siguiente = METRICAS.length - 1;
    else return;

    event.preventDefault();
    setMetricaId(METRICAS[siguiente].id);
    event.currentTarget.parentElement.querySelectorAll('[role="tab"]')[siguiente].focus();
  };

  return (
    <section className="panel" data-tour="gondola-metrics">
      <div className="panel-head">
        <h3>Métricas por góndola</h3>
        <div className="metric-engine-status" aria-live="polite">
          {multiprocessingUsed && <span>Procesado con multiprocessing</span>}
          {sparkMetricas?.engine === 'apache_spark' && <span>Métricas calculadas con Apache Spark</span>}
          {sparkMetricas?.engine === 'python_fallback' && <span>Métricas históricas: fallback Python</span>}
        </div>
      </div>
      <div className="interaction-metric-tabs" role="tablist" aria-label="Métrica por góndola">
            {METRICAS.map((item) => (
              <button
                key={item.id}
                id={`interaction-tab-${item.id}`}
                type="button"
                role="tab"
                aria-selected={metricaId === item.id}
                aria-controls="interaction-chart-panel"
                tabIndex={metricaId === item.id ? 0 : -1}
                className={metricaId === item.id ? 'is-active' : ''}
                onClick={() => setMetricaId(item.id)}
                onKeyDown={manejarTeclas}
              >
                {item.etiqueta}
              </button>
            ))}
          </div>
          <div className="panel-body interaction-chart-body">
          {zonas.length ? (
            <>
          <div id="interaction-chart-panel" role="tabpanel" aria-labelledby={`interaction-tab-${metricaId}`}>
            <div className="interaction-chart-scroll">
              <div className="interaction-chart" style={{ minWidth: Math.max(420, zonas.length * 112) }}>
                <ResponsiveContainer>
                  <BarChart data={datos} margin={{ top: 24, right: 14, bottom: 50, left: 10 }}>
                    <CartesianGrid stroke="var(--panel-border)" vertical={false} strokeDasharray="3 4" />
                    <XAxis
                      dataKey="zone_id"
                      interval={0}
                      angle={-18}
                      textAnchor="end"
                      height={62}
                      tick={{ fill: 'var(--ink-muted)', fontSize: 10 }}
                      tickLine={{ stroke: 'var(--panel-border)' }}
                      axisLine={{ stroke: 'var(--panel-border)' }}
                      label={{ value: 'Góndola', position: 'insideBottom', offset: -43, fill: 'var(--ink-muted)', fontSize: 12 }}
                    />
                    <YAxis
                      domain={doble || formatoValor === 'porcentaje' ? [0, 100] : [0, Math.max(maxDato, 1)]}
                      ticks={doble || formatoValor === 'porcentaje' ? [0, 25, 50, 75, 100] : undefined}
                      allowDecimals={metrica.formato === 'decimal'}
                      tickFormatter={valorEje}
                      tick={{ fill: 'var(--ink-muted)', fontSize: 11 }}
                      tickLine={false}
                      axisLine={false}
                      label={{ value: metrica.unidad === '%' ? `${metrica.etiqueta} (%)` : metrica.unidad === 'segundos' ? 'Dwell (s)' : 'Flujo (visitantes)', angle: -90, position: 'insideLeft', fill: 'var(--ink-muted)', fontSize: 12 }}
                    />
                    <Tooltip content={<TooltipGondola />} cursor={{ fill: 'rgba(62, 46, 34, 0.06)' }} />
                    {series.map((serie) => (
                      <Bar
                        key={serie.clave}
                        dataKey={serie.clave}
                        name={serie.etiqueta}
                        fill={serie.color}
                        radius={[5, 5, 0, 0]}
                      >
                        <LabelList
                          dataKey={serie.clave}
                          position="top"
                          formatter={(valor) => formatear(Number(valor), formatoValor)}
                          fill="var(--ink)"
                          fontSize={11}
                        />
                      </Bar>
                    ))}
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          </div>
          <div className="interaction-chart-legend" aria-label="Leyenda del gráfico">
            {series.map((serie) => (
              <span key={serie.clave}>
                <i style={{ background: serie.color }} />
                {serie.etiqueta}{serie.clave === 'flujo' ? ' (visitantes)' : serie.clave === 'dwell' ? ' (segundos)' : ' (%)'}
              </span>
            ))}
          </div>
          {sparkMetricas?.metricas?.length > 0 && (
            <details className="spark-metrics-details">
              <summary>Agregado histórico por góndola · {sparkMetricas.metricas.length} zonas</summary>
              <div className="spark-metrics-scroll">
                <table className="spark-metrics-table">
                  <thead>
                    <tr>
                      <th>Góndola</th><th>Flujo</th><th>Dwell medio</th>
                      <th>Interacción</th><th>Rechazo</th><th>Rendimiento</th><th>Análisis</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sparkMetricas.metricas.map((fila) => (
                      <tr key={fila.zone_id}>
                        <th scope="row">{fila.zone_id}</th>
                        <td>{Number(fila.flujo_total).toLocaleString('es-CO')}</td>
                        <td>{Number(fila.dwell_promedio_s).toFixed(2)} s</td>
                        <td>{Number(fila.interaccion_media_pct).toFixed(2)}%</td>
                        <td>{Number(fila.rechazo_medio_pct).toFixed(2)}%</td>
                        <td>{Number(fila.rendimiento_pct).toFixed(2)}%</td>
                        <td>{fila.analisis_count}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {sparkMetricas.mensaje && <p className="spark-metrics-message">{sparkMetricas.mensaje}</p>}
            </details>
          )}
          </>
        ) : (
          <p className="panel-empty">Analiza un video para ver las métricas por góndola.</p>
        )}
      </div>
    </section>
  );
}