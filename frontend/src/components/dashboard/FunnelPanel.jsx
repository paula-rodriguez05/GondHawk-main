const PASOS = [
  { key: 'visitas', label: 'Pasan por la zona', color: 'var(--accent)' },
  { key: 'se_detiene', label: 'Se detienen / miran', color: 'var(--cyan)' },
  { key: 'toma_producto', label: 'Toman producto', color: 'var(--success)' },
  { key: 'devuelve', label: 'Devuelven producto', color: 'var(--warning)' },
  { key: 'se_lo_lleva', label: 'Posibles conversiones', color: 'var(--danger)' },
];

/**
 * Embudo físico de compra.
 *
 * El ancho de cada barra es relativo al primer paso, no al máximo absoluto:
 * así se lee la caída entre etapas, que es la información que importa para
 * space management.
 */
export function FunnelPanel({ total, zonas, zonaSeleccionada, onSeleccionar }) {
  const datos = zonaSeleccionada
    ? zonas.find((z) => z.zone_id === zonaSeleccionada)?.embudo ?? {}
    : {
        visitas: total?.visitas ?? 0,
        se_detiene: total?.se_detiene ?? 0,
        toma_producto: total?.toma_producto ?? 0,
        devuelve: total?.devuelve ?? 0,
        se_lo_lleva: total?.se_lo_lleva ?? 0,
      };

  const base = datos.visitas || 1;

  return (
    <section className="panel" data-tour="interactions">
      <div className="panel-head">
        <h3>Embudo físico de compra</h3>
        <select
          value={zonaSeleccionada ?? ''}
          onChange={(e) => onSeleccionar(e.target.value || null)}
          className="panel-select"
        >
          <option value="">Toda la tienda</option>
          {zonas.map((z) => (
            <option key={z.zone_id} value={z.zone_id}>{z.zone_id}</option>
          ))}
        </select>
      </div>

      <ul className="funnel-list">
        {PASOS.map((paso, i) => {
          const valor = datos[paso.key] ?? 0;
          const pct = Math.round((valor / base) * 100);
          return (
            <li key={paso.key} className="funnel-row">
              <span className="funnel-step">{i + 1}</span>
              <div className="funnel-body">
                <p className="funnel-value">{valor.toLocaleString('es-CO')}</p>
                <p className="funnel-label">{paso.label}</p>
              </div>
              <div className="funnel-bar-wrap">
                <div
                  className="funnel-bar"
                  style={{ width: `${Math.max(pct, 2)}%`, background: paso.color }}
                />
              </div>
              <span className="funnel-pct">{pct} %</span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
