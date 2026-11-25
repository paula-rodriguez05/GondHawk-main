const ESTADO = {
  caliente: { label: 'Excelente', clase: 'badge-ok' },
  templada: { label: 'Mejorable', clase: 'badge-warn' },
  fria: { label: 'Crítica', clase: 'badge-bad' },
  sin_datos: { label: 'Sin datos', clase: 'badge-muted' },
};

function pct(v) {
  return `${Math.round((v ?? 0) * 100)} %`;
}

/** Rendimiento por góndola. Las columnas salen del embudo real, sin puntajes compuestos. */
export function PerformanceTable({ zonas, onSeleccionar, zonaSeleccionada }) {
  const totalFlujo = zonas.reduce((total, zona) => total + (zona.embudo?.visitas ?? 0), 0);

  if (!zonas.length) {
    return (
      <section className="panel" data-tour="performance">
        <div className="panel-head"><h3>Rendimiento por góndola</h3></div>
        <p className="panel-empty">Analiza un video para ver el rendimiento por zona.</p>
      </section>
    );
  }

  return (
    <section className="panel" data-tour="performance">
      <div className="panel-head"><h3>Rendimiento por góndola</h3></div>
      <div className="table-wrap performance-table-wrap" tabIndex="0" aria-label="Tabla de rendimiento; desplázate horizontalmente para ver todas las columnas">
        <table className="data-table performance-table">
          <thead>
            <tr>
              <th>Góndola</th><th>Flujo</th><th>% del flujo</th><th>Dwell</th>
              <th>Interacción</th><th>Rechazo</th><th>Rendimiento</th><th>Estado</th>
            </tr>
          </thead>
          <tbody>
            {zonas.map((z) => {
              const estado = ESTADO[z.temperatura] ?? ESTADO.sin_datos;
              const flujo = z.embudo?.visitas ?? 0;
              const rendimiento = (z.tasa_interaccion ?? 0) * (1 - (z.tasa_rechazo ?? 0));
              return (
                <tr
                  key={z.zone_id}
                  onClick={() => onSeleccionar(z.zone_id === zonaSeleccionada ? null : z.zone_id)}
                  className={z.zone_id === zonaSeleccionada ? 'row-active' : ''}
                >
                  <td>{z.zone_id}</td>
                  <td>{flujo.toLocaleString('es-CO')}</td>
                  <td>{totalFlujo ? `${Math.round((flujo / totalFlujo) * 100)} %` : '0 %'}</td>
                  <td>{(z.dwell_promedio_s ?? 0).toFixed(1)} s</td>
                  <td>{pct(z.tasa_interaccion)}</td>
                  <td>{pct(z.tasa_rechazo)}</td>
                  <td>{pct(rendimiento)}</td>
                  <td><span className={`badge ${estado.clase}`}>{estado.label}</span></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
