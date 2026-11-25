import { useCallback, useEffect, useState } from 'react';
import { DATA_SOURCES } from '../../config/dataConfig';

function fecha(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString('es-CO', { dateStyle: 'short', timeStyle: 'short' });
}

function porcentaje(valor) {
  return typeof valor === 'number' ? `${Math.round(valor * 100)}%` : '—';
}

/**
 * Historial de análisis. Lista las corridas guardadas y permite reabrir una.
 *
 * El resumen que muestra viene ya aplanado del backend, así que la lista no
 * tiene que descargar el detalle completo de cada corrida para pintarse.
 */
export function HistoryPanel({ onAbrir, recargar }) {
  const [analisis, setAnalisis] = useState([]);
  const [estadisticas, setEstadisticas] = useState(null);
  const [error, setError] = useState(null);
  const [cargando, setCargando] = useState(true);

  const cargar = useCallback(async (sigueVigente = () => true) => {
    try {
      const res = await fetch(DATA_SOURCES.historial);
      if (!sigueVigente()) return;
      if (!res.ok) throw new Error('No se pudo cargar el historial.');
      const payload = await res.json();
      if (!sigueVigente()) return;
      setAnalisis(Array.isArray(payload.analisis) ? payload.analisis : []);
      setEstadisticas(payload.estadisticas ?? null);
      setError(null);
    } catch (err) {
      if (!sigueVigente()) return;
      setError(err instanceof Error ? err.message : 'Error al cargar el historial.');
    } finally {
      if (sigueVigente()) setCargando(false);
    }
  }, []);

  useEffect(() => {
    // Carga inicial y recarga tras cada análisis nuevo. El estado solo se
    // actualiza dentro del callback asíncrono y se descarta si el componente
    // se desmontó antes de que responda el backend.
    let vigente = true;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    cargar(() => vigente);
    return () => {
      vigente = false;
    };
  }, [cargar, recargar]);

  const abrir = async (id) => {
    try {
      const res = await fetch(DATA_SOURCES.analisis(id));
      if (!res.ok) throw new Error('No se pudo abrir el análisis.');
      const detalle = await res.json();
      onAbrir?.(detalle.detalle ?? detalle, id);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error al abrir el análisis.');
    }
  };

  const eliminar = async (id, event) => {
    event.stopPropagation();
    try {
      await fetch(DATA_SOURCES.analisis(id), { method: 'DELETE' });
      cargar();
    } catch {
      setError('No se pudo eliminar el análisis.');
    }
  };

  return (
    <div className="history-view" data-tour="history">
      <section className="history-saved-card" aria-labelledby="saved-analysis-title">
        <div className="history-saved-heading">
          <div>
            <h2 id="saved-analysis-title">Historial de análisis guardados</h2>
            {estadisticas?.total_analisis > 0 && (
              <p>
                {estadisticas.total_analisis} análisis · interacción media{' '}
                {porcentaje(estadisticas.promedio_tasa_interaccion)}
              </p>
            )}
          </div>
          <button type="button" onClick={() => cargar()}>
            {cargando ? 'Cargando...' : 'Actualizar'}
          </button>
        </div>

        {error && <p className="history-error">{error}</p>}

        {analisis.length === 0 && !cargando ? (
          <p className="history-empty">Todavía no hay análisis guardados.</p>
        ) : (
          <ul className="history-saved-list">
            {analisis.map((item) => (
              <li key={item.id}>
                <button type="button" onClick={() => abrir(item.id)} className="history-saved-row">
                  <span className="history-saved-name">
                    <strong>{item.video}</strong>
                    <small>{fecha(item.fecha)}</small>
                  </span>
                  <span className="history-saved-metrics">
                    <span>{item.resumen?.visitas ?? 0} visitas</span>
                    <span>{porcentaje(item.resumen?.tasa_interaccion)}</span>
                  </span>
                </button>
                <button type="button" onClick={(event) => eliminar(item.id, event)} className="history-delete-button">
                  Eliminar
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
