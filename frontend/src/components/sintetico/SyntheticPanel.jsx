import { useCallback, useEffect, useRef, useState } from 'react';
import { DATA_SOURCES } from '../../config/dataConfig';
import { normalizeAnalysisResponse } from '../../hooks/useDashboardData';
import { VideoPanel } from '../video/VideoPanel';
import { FunnelPanel } from '../dashboard/FunnelPanel';
import { PerformanceTable } from '../dashboard/PerformanceTable';

const DURACIONES = [30, 60, 90, 120];
const PERSONAS = [8, 12, 16, 20];
const GONDOLAS = [2, 3, 4, 5, 6];

function pct(v) {
  return typeof v === 'number' ? `${Math.round(v * 100)} %` : '—';
}

function mmss(segundos) {
  const s = Math.max(0, Math.round(segundos));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

/**
 * Vista de escena sintética 3D.
 *
 * La generación corre en el servidor y esta vista consulta el progreso cada
 * dos segundos. Antes la petición esperaba el render completo —más de diez
 * minutos para 90 s de video— y el navegador agotaba el tiempo de espera sin
 * que el usuario supiera si seguía vivo.
 *
 * Al estar en su propia ventana, el tablero principal no se ve afectado
 * mientras corre: se puede volver a él y seguir consultando análisis.
 */
export function SyntheticPanel({ onAnalisis }) {
  const [duracion, setDuracion] = useState(60);
  const [personas, setPersonas] = useState(12);
  const [gondolas, setGondolas] = useState(3);
  const [trabajo, setTrabajo] = useState(null);
  const [error, setError] = useState(null);
  const [transcurrido, setTranscurrido] = useState(0);
  // Los resultados de la escena 3D viven AQUÍ, no en el tablero principal.
  // Antes se enviaban al tablero y la vista 3D quedaba vacía al volver a
  // ella: el usuario perdía de vista lo que acababa de generar.
  const [datos, setDatos] = useState(null);
  const [zonaSeleccionada, setZonaSeleccionada] = useState(null);
  const intervalo = useRef(null);
  const cronometro = useRef(null);

  const enCurso = trabajo?.estado === 'renderizando' || trabajo?.estado === 'analizando';
  const densidadAlta = duracion / personas < 4;

  const limpiar = useCallback(() => {
    if (intervalo.current) clearInterval(intervalo.current);
    if (cronometro.current) clearInterval(cronometro.current);
    intervalo.current = null;
    cronometro.current = null;
  }, []);

  useEffect(() => limpiar, [limpiar]);

  const consultar = useCallback(
    async (jobId) => {
      try {
        const res = await fetch(`${DATA_SOURCES.apiBase}/api/sintetico/estado/${jobId}`);
        if (!res.ok) throw new Error('No se pudo consultar el estado.');
        const estado = await res.json();
        setTrabajo(estado);

        if (estado.estado === 'listo') {
          limpiar();
          setDatos(normalizeAnalysisResponse(estado.resultado, Date.now()));
          onAnalisis?.(estado.resultado);
        } else if (estado.estado === 'error') {
          limpiar();
          setError(estado.error ?? 'La generación falló.');
        }
      } catch (err) {
        limpiar();
        setError(err instanceof Error ? err.message : 'Error consultando el estado.');
      }
    },
    [limpiar, onAnalisis],
  );

  const generar = async () => {
    setError(null);
    setTranscurrido(0);
    try {
      const url = `${DATA_SOURCES.apiBase}/api/sintetico/generar?duracion=${duracion}&personas=${personas}&gondolas=${gondolas}&seed=7`;
      const res = await fetch(url, { method: 'POST' });
      const payload = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(payload.detail ?? 'No se pudo iniciar la generación.');

      setTrabajo(payload);
      limpiar();
      intervalo.current = setInterval(() => consultar(payload.job_id), 2000);
      cronometro.current = setInterval(() => setTranscurrido((t) => t + 1), 1000);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error al iniciar.');
    }
  };

  const resultado = trabajo?.estado === 'listo' ? trabajo.resultado : null;
  const exactitud = resultado?.exactitud;
  const progreso = Math.round((trabajo?.progreso ?? 0) * 100);
  const restante = trabajo?.estimado_s ? trabajo.estimado_s - transcurrido : null;

  return (
    <div className="dashboard-grid dashboard-grid-2">
      <section className="panel">
        <div className="panel-head">
          <h3>Generar escena 3D</h3>
          <span className="badge badge-ok">Sin personas reales</span>
        </div>

        <div className="panel-body">
          <p className="text-sm text-[var(--ink-muted)]">
            Construye una tienda en 3D con compradores virtuales y la analiza con el
            mismo pipeline. Como el generador decide qué hace cada persona, se puede
            medir la exactitud del sistema: con video real eso exigiría anotar a mano
            cada toma y cada devolución.
          </p>

          <div className="analysis-options mt-3">
            <label className="analysis-option">
              <span>
                Duración
                <small>El render produce unos 3 frames por segundo.</small>
              </span>
              <select
                value={duracion}
                onChange={(e) => setDuracion(Number(e.target.value))}
                disabled={enCurso}
              >
                {DURACIONES.map((d) => (
                  <option key={d} value={d}>{d} s</option>
                ))}
              </select>
            </label>

            <label className="analysis-option">
              <span>
                Personas
                <small>Repartidas a lo largo de todo el video.</small>
              </span>
              <select
                value={personas}
                onChange={(e) => setPersonas(Number(e.target.value))}
                disabled={enCurso}
              >
                {PERSONAS.map((p) => (
                  <option key={p} value={p}>{p}</option>
                ))}
              </select>
            </label>

            <label className="analysis-option">
              <span>
                Góndolas
                <small>Cantidad de estanterías del mundo 3D.</small>
              </span>
              <select
                value={gondolas}
                onChange={(e) => setGondolas(Number(e.target.value))}
                disabled={enCurso}
              >
                {GONDOLAS.map((g) => (
                  <option key={g} value={g}>{g}</option>
                ))}
              </select>
            </label>
          </div>

          {densidadAlta && (
            <p className="mt-2 text-sm text-amber-400">
              Densidad alta ({(duracion / personas).toFixed(1)} s por persona): las
              personas se solaparán frente al lineal y el detector fusionará sus cajas.
            </p>
          )}

          <button
            type="button"
            onClick={generar}
            disabled={enCurso}
            className="analyze-button mt-3"
          >
            {enCurso ? 'Generando…' : 'Generar escena 3D'}
          </button>

          {trabajo && enCurso && (
            <div className="mt-4">
              <div className="flex items-center justify-between text-sm text-[var(--ink-muted)]">
                <span>{trabajo.etapa}</span>
                <span>{progreso} %</span>
              </div>
              <div className="funnel-bar-wrap mt-2">
                <div
                  className="funnel-bar"
                  style={{ width: `${Math.max(progreso, 2)}%`, background: 'var(--accent)' }}
                />
              </div>
              <p className="mt-2 text-sm text-[var(--ink-muted)]">
                {mmss(transcurrido)} transcurridos
                {restante > 0 ? ` · quedan unos ${mmss(restante)}` : ''}
                {' · '}puedes volver al tablero, esto sigue en el servidor.
              </p>
            </div>
          )}

          {error && (
            <pre className="mt-3 max-h-40 overflow-auto whitespace-pre-wrap rounded-xl border border-red-400/30 p-3 text-sm text-red-400">
              {error}
            </pre>
          )}
        </div>
      </section>

      <section className="panel">
        <div className="panel-head"><h3>Exactitud frente a la verdad conocida</h3></div>
        <div className="panel-body">
          {!resultado && (
            <p className="text-base text-[var(--ink-muted)]">
              Genera una escena para medir precisión y recall de la detección de eventos.
            </p>
          )}

          {resultado && (
            <>
              <p className="text-base">{resultado.mensaje}</p>

              {exactitud?.por_tipo?.length > 0 ? (
                <div className="table-wrap mt-3">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Evento</th><th>Reales</th><th>Detectados</th>
                        <th>Precisión</th><th>Recall</th><th>F1</th>
                      </tr>
                    </thead>
                    <tbody>
                      {exactitud.por_tipo.map((fila) => (
                        <tr key={fila.event_type}>
                          <td>{fila.event_type}</td>
                          <td>{fila.esperados}</td>
                          <td>{fila.detectados}</td>
                          <td>{pct(fila.precision)}</td>
                          <td>{pct(fila.recall)}</td>
                          <td>{pct(fila.f1)}</td>
                        </tr>
                      ))}
                      {exactitud.global && (
                        <tr className="row-active">
                          <td><strong>Global</strong></td>
                          <td>—</td>
                          <td>{exactitud.global.aciertos}</td>
                          <td>{pct(exactitud.global.precision)}</td>
                          <td>{pct(exactitud.global.recall)}</td>
                          <td>{pct(exactitud.global.f1)}</td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="mt-3 text-sm text-[var(--ink-muted)]">
                  No se pudo calcular la exactitud de esta corrida.
                </p>
              )}

              <p className="mt-4 text-sm text-[var(--ink-muted)]">
                El análisis también quedó guardado en el historial.
              </p>
            </>
          )}
        </div>
      </section>

      {datos && (
        <>
          <section className="panel">
            <div className="panel-head">
              <h3>Video 3D analizado</h3>
              <span className="badge badge-ok">Escena sintética</span>
            </div>
            <VideoPanel
              videoUrl={datos.videoAnotadoUrl}
              zonasUrl={datos.zonasPropuestasUrl}
              embebido
            />
          </section>

          <section className="panel">
            <div className="panel-head"><h3>Mapa de calor de la escena 3D</h3></div>
            {datos.heatmapUrl ? (
              <img src={datos.heatmapUrl} alt="Mapa de calor de la escena sintética" className="w-full" />
            ) : (
              <p className="panel-empty">Sin mapa de calor para esta escena.</p>
            )}
          </section>

          <FunnelPanel
            total={datos.totalGlobal}
            zonas={datos.zonasGondola}
            zonaSeleccionada={zonaSeleccionada}
            onSeleccionar={setZonaSeleccionada}
          />

          <PerformanceTable
            zonas={datos.zonasGondola}
            zonaSeleccionada={zonaSeleccionada}
            onSeleccionar={setZonaSeleccionada}
          />
        </>
      )}
    </div>
  );
}
