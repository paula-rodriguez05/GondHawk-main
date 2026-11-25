import { useEffect, useMemo, useRef, useState } from 'react';
import { HomeIntro } from './components/home/HomeIntro';
import { useDashboardData } from './hooks/useDashboardData';
import { resumenGlobal } from './utils/aggregate';
import { Header } from './components/layout/Header';
import { KpiStrip } from './components/kpis/KpiStrip';
import { ZoneShelfPanel } from './components/zones/ZoneShelfPanel';
import { HeatmapPanel } from './components/heatmap/HeatmapPanel';
import { ZoneFunnelTable } from './components/funnel/ZoneFunnelTable';
import { AlertsPanel } from './components/alerts/AlertsPanel';
import { VideoPanel } from './components/video/VideoPanel';
import { SyntheticPanel } from './components/sintetico/SyntheticPanel';
import { StoreMapPanel } from './components/storemap/StoreMapPanel';
import { NetworkPanel } from './components/network/NetworkPanel';
import { FunnelPanel } from './components/dashboard/FunnelPanel';
import { PerformanceTable } from './components/dashboard/PerformanceTable';
import { InteractionRateChart } from './components/dashboard/InteractionRateChart';
import { DayRecapPanel } from './components/dashboard/DayRecapPanel';
import { HistoryPanel } from './components/history/HistoryPanel';
import { ReportDownloads } from './components/reports/ReportDownloads';
import { ProductTour } from './components/product-tour/ProductTour';
import { ANALYSIS_DEFAULTS, DATA_SOURCES, buildAnalyzeUrl } from './config/dataConfig';

const TABS = [
  { id: 'cargar', label: 'Cargar video' },
  { id: 'video', label: 'Video y mapas' },
  { id: 'rendimiento', label: 'Rendimiento' },
  { id: 'detalle', label: 'Detalle' },
  { id: 'historial', label: 'Historial' },
];

export default function App() {
  const { data, updateFromAnalysis, resetData } = useDashboardData();
  const [selectedFile, setSelectedFile] = useState(null);
  const [selectedFiles, setSelectedFiles] = useState([]);
  const [processing, setProcessing] = useState(false);
  const [progress, setProgress] = useState(0);
  const [analysisMessage, setAnalysisMessage] = useState('Listo para analizar un video.');
  const [lastResult, setLastResult] = useState(null);
  const [analysisCompleted, setAnalysisCompleted] = useState(false);
  const [multiprocessingUsed, setMultiprocessingUsed] = useState(false);
  const [sparkMetricas, setSparkMetricas] = useState(null);
  const fileInputRef = useRef(null);
  const timerRef = useRef(null);
  const [zonasAuto, setZonasAuto] = useState(ANALYSIS_DEFAULTS.zonasAuto);
  const [frameSkip, setFrameSkip] = useState(ANALYSIS_DEFAULTS.frameSkip);
  const [recomendaciones, setRecomendaciones] = useState(null);
  const [fuenteReco, setFuenteReco] = useState(null);
  const [historialKey, setHistorialKey] = useState(0);
  const [zonaSeleccionada, setZonaSeleccionada] = useState(null);
  // Dos pantallas dentro de la misma aplicación: el tablero y la escena 3D.
  // La generación 3D tarda minutos, así que vive en su propia vista para no
  // interferir con el uso normal del tablero.
  const [vista, setVista] = useState('tablero');
  const [tab, setTab] = useState('cargar');
  const [tourOpen, setTourOpen] = useState(false);
  const [videoTime, setVideoTime] = useState(0);
  const [introDone, setIntroDone] = useState(false);
  const [syntheticKey, setSyntheticKey] = useState(0);

  useEffect(() => {
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []);

  useEffect(() => {
    if (tab !== 'rendimiento') return undefined;

    const controller = new AbortController();
    fetch(DATA_SOURCES.sparkMetricas, { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error('No se pudieron cargar las métricas históricas.');
        return response.json();
      })
      .then((payload) => setSparkMetricas(payload))
      .catch((error) => {
        if (!controller.signal.aborted) {
          setSparkMetricas({ engine: 'unavailable', mensaje: error.message, metricas: [] });
        }
      });

    return () => controller.abort();
  }, [tab, historialKey]);

  const currentData = useMemo(() => {
    if (!data) return null;
    return {
      ...data,
      totalGlobal: data.totalGlobal ?? { visitas: 0, tasa_interaccion: 0, tasa_rechazo: 0 },
      zonasGondola: data.zonasGondola ?? [],
      alertas: data.alertas ?? [],
    };
  }, [data]);

  const resumen = resumenGlobal(currentData.totalGlobal, currentData.zonasGondola);

  if (!introDone) {
    return <HomeIntro onEnter={() => setIntroDone(true)} />;
  }

  const handleAnalyze = async () => {
    if (!selectedFile) {
      setAnalysisMessage('Selecciona un video antes de analizar.');
      return;
    }

    const procesarLote = selectedFiles.length > 1;
    setProcessing(true);
    setMultiprocessingUsed(false);
    setProgress(0);
    resetData();
    setLastResult(null);
    setAnalysisCompleted(false);
    setAnalysisMessage(
      procesarLote
        ? `Analizando ${selectedFiles.length} videos en paralelo...`
        : `Analizando ${selectedFile.name}...`,
    );

    if (timerRef.current) clearInterval(timerRef.current);
    timerRef.current = setInterval(() => {
      setProgress((prev) => {
        const next = prev + 12;
        return next >= 100 ? 100 : next;
      });
    }, 220);

    try {
      const formData = new FormData();
      if (procesarLote) {
        selectedFiles.forEach((file) => formData.append('files', file));
      } else {
        formData.append('file', selectedFile);
      }

      const parametros = new URLSearchParams({
        zonas_auto: String(Boolean(zonasAuto)),
        frame_skip: String(frameSkip),
      });
      const url = procesarLote
        ? `${DATA_SOURCES.analyzeVideosBatch}?${parametros.toString()}`
        : buildAnalyzeUrl({ zonasAuto, frameSkip });
      const response = await fetch(url, {
        method: 'POST',
        body: formData,
      });

      let payload = {};
      try {
        payload = await response.json();
      } catch {
        payload = {};
      }

      if (!response.ok) {
        const detail = typeof payload?.detail === 'string'
          ? payload.detail
          : typeof payload?.message === 'string'
            ? payload.message
            : 'El backend rechazó la solicitud.';
        throw new Error(detail);
      }

      let resultadoVisible = payload;
      if (procesarLote) {
        const resultados = Array.isArray(payload.resultados) ? payload.resultados : [];
        setMultiprocessingUsed(payload.procesamiento === 'multiprocessing');
        const correctos = resultados.filter((resultado) => resultado.status === 'ok');
        if (!correctos.length) {
          const primerError = resultados.find((resultado) => resultado.error)?.error;
          throw new Error(primerError ?? 'No se pudo analizar ninguno de los videos.');
        }
        resultadoVisible = correctos[correctos.length - 1];
        const errores = resultados.length - correctos.length;
        setLastResult({
          mensaje: `${correctos.length} de ${resultados.length} videos analizados con multiprocessing.${errores ? ` ${errores} con error.` : ''}`,
        });
      } else {
        setLastResult(payload);
        setMultiprocessingUsed(false);
      }

      updateFromAnalysis(resultadoVisible, Date.now());
      setAnalysisCompleted(true);
      setHistorialKey((k) => k + 1);

      // El pipeline ya devuelve las recomendaciones dentro de las métricas.
      // Solo se piden aparte cuando no vienen, que es el caso de los análisis
      // guardados antes de ese cambio.
      const yaVienen = (resultadoVisible?.interaction?.recomendaciones ?? []).length > 0;
      if (resultadoVisible?.analisis_id && !yaVienen) {
        fetch(DATA_SOURCES.recomendaciones(resultadoVisible.analisis_id))
          .then((r) => (r.ok ? r.json() : null))
          .then((reco) => {
            if (!reco) return;
            setRecomendaciones(reco.recomendaciones ?? []);
            setFuenteReco(reco.fuente ?? null);
          })
          .catch(() => { });
      }
      const realMessage = procesarLote
        ? `${selectedFiles.length} videos procesados; se muestran las métricas del último análisis correcto.`
        : typeof payload?.message === 'string'
          ? payload.message
          : typeof payload?.status === 'string'
            ? payload.status
            : `Análisis completado para ${selectedFile.name}.`;
      setAnalysisMessage(realMessage);
    } catch (err) {
      const realError = err instanceof Error ? err.message : 'No se pudo completar la solicitud.';
      setLastResult((prev) => prev ?? { mensaje: realError });
      setAnalysisMessage(realError);
    } finally {
      if (timerRef.current) clearInterval(timerRef.current);
      setProgress(100);
      setTimeout(() => setProcessing(false), 500);
    }
  };

  const handleClearInformation = () => {
    if (timerRef.current) clearInterval(timerRef.current);
    resetData();
    setSelectedFile(null);
    setSelectedFiles([]);
    setProcessing(false);
    setProgress(0);
    setAnalysisMessage('Listo para analizar un video.');
    setLastResult(null);
    setAnalysisCompleted(false);
    setMultiprocessingUsed(false);
    setRecomendaciones(null);
    setFuenteReco(null);
    if (fileInputRef.current) fileInputRef.current.value = '';
    // La escena 3D guarda su propio estado (trabajo, resultado, error) en
    // SyntheticPanel; cambiar su key la remonta y así queda tan limpia como
    // el resto del tablero.
    setSyntheticKey((k) => k + 1);
  };

  return (
    <div className="page-shell">
      <Header
        vista={vista}
        onToggleVista={() => setVista(vista === 'sintetico' ? 'tablero' : 'sintetico')}
        onOpenTour={() => setTourOpen(true)}
      />
      <div className="app-shell">
      <main className="main-content">
        {/* Las dos vistas se mantienen MONTADAS y se oculta la inactiva con
            CSS. Con un ternario, React desmontaba la vista al cambiar y se
            perdía todo su estado: al volver de la escena 3D había que
            regenerarla desde cero, y el sondeo de progreso se cortaba a mitad
            del render. */}
        <div className="content-stack" hidden={vista !== 'sintetico'}>
          <section className="analysis-card">
            <div className="analysis-card-head">
              <div>
                <p className="eyebrow">Datos sintéticos</p>
                <h2>Escena 3D de validación</h2>
                <p className="muted">
                  Genera una tienda virtual con compradores en 3D para medir la
                  exactitud del sistema sin grabar a ninguna persona.
                </p>
              </div>
              <div className="upload-actions">
                <button
                  type="button"
                  onClick={() => setVista('tablero')}
                  className="analyze-button"
                >
                  Volver al tablero
                </button>
              </div>
            </div>
          </section>

          <SyntheticPanel
            key={syntheticKey}
            onAnalisis={() => {
              // La escena 3D muestra sus propios resultados en esta vista y
              // NO toca el tablero principal: al volver al tablero debe
              // seguir viéndose el último video real analizado. Solo se
              // refresca el historial, donde la escena queda archivada.
              setHistorialKey((k) => k + 1);
            }}
          />
        </div>

        <div className="content-stack" hidden={vista !== 'tablero'}>
          <nav className="tab-bar" aria-label="Secciones del tablero">
            {TABS.map((t) => (
              <button
                key={t.id}
                type="button"
                className={`tab-button ${tab === t.id ? 'active' : ''}`}
                onClick={() => setTab(t.id)}
              >
                {t.label}
              </button>
            ))}
          </nav>

          {/* Cada pestaña queda MONTADA y se oculta con CSS (mismo motivo que
              la vista tablero/escena 3D): así el video no se reinicia ni el
              historial se vuelve a pedir al cambiar de pestaña. */}
          <div className="tab-frame">
            <div className="tab-panel" hidden={tab !== 'cargar'}>
              <section id="cargar" className="analysis-card">
                <div className="analysis-card-head">
                  <div><p className="eyebrow">Análisis de video</p><h2>Carga y procesamiento del flujo</h2><p className="muted">Selecciona un archivo para generar las métricas de esta sesión.</p></div>
                  <div className="upload-actions">
                    {analysisCompleted ? (
                      <button type="button" onClick={handleClearInformation} className="analyze-button">Limpiar información</button>
                    ) : (
                      <>
                        <label className="upload-button" data-tour="upload-video">
                          <input
                            ref={fileInputRef}
                            type="file"
                            accept="video/*"
                            multiple
                            className="hidden"
                            onChange={(event) => {
                              const archivos = Array.from(event.target.files ?? []);
                              setSelectedFiles(archivos);
                              setSelectedFile(archivos[0] ?? null);
                            }}
                          />
                          {selectedFiles.length > 1
                            ? `Cambiar ${selectedFiles.length} videos`
                            : selectedFile ? 'Cambiar video' : 'Seleccionar videos'}
                        </label>
                        <button type="button" onClick={handleAnalyze} disabled={processing} className="analyze-button" data-tour="start-analysis">
                          {processing ? 'Analizando...' : 'Analizar video'}
                        </button>
                      </>
                    )}
                  </div>
                </div>

                <div className="analysis-options" data-tour="analysis-options">
                  <label className="analysis-option">
                    <input
                      type="checkbox"
                      checked={zonasAuto}
                      onChange={(event) => setZonasAuto(event.target.checked)}
                    />
                    <span>
                      Detectar zonas automáticamente
                      <small>Recomendado. Sin esto se usan las zonas del video de calibración.</small>
                    </span>
                  </label>
                  <label className="analysis-option">
                    <span>
                      Frames analizados
                      <small>Saltar frames acelera el análisis pero fragmenta el seguimiento.</small>
                    </span>
                    <select value={frameSkip} onChange={(event) => setFrameSkip(Number(event.target.value))}>
                      <option value={1}>Todos (mejor precisión)</option>
                      <option value={2}>1 de cada 2</option>
                      <option value={3}>1 de cada 3 (más rápido)</option>
                    </select>
                  </label>
                </div>

                <div className="file-status">
                  <div className="min-w-0"><p className="eyebrow">Archivo seleccionado</p><p className="mt-1 truncate text-base text-[var(--ink)]">
                    {selectedFiles.length > 1
                      ? `${selectedFiles.length} videos seleccionados`
                      : selectedFile ? selectedFile.name : 'Sin archivo seleccionado'}
                  </p></div>

                  <div className="progress-wrap"><div className="progress-ring"><svg viewBox="0 0 100 100">
                    <circle cx="50" cy="50" r="42" stroke="rgba(62,46,34,0.15)" strokeWidth="10" fill="none" />
                    <circle
                      cx="50"
                      cy="50"
                      r="42"
                      stroke="var(--accent)"
                      strokeWidth="10"
                      strokeLinecap="round"
                      fill="none"
                      strokeDasharray={264}
                      strokeDashoffset={264 - (264 * progress) / 100}
                      style={{ transition: 'stroke-dashoffset 0.25s ease' }}
                    />
                  </svg><span>{progress}%</span></div><div><p>{processing ? 'Procesando video' : 'Listo para analizar'}</p><p>{analysisMessage}</p></div></div>
                </div>

                {lastResult && (
                  <div className="result-message">
                    {/* El backend siempre manda `mensaje`; se lee primero. Los
                        otros dos campos cubren errores de FastAPI (detail) y
                        respuestas antiguas. */}
                    {lastResult.mensaje ?? lastResult.detail ?? lastResult.message ?? 'Análisis completado.'}
                  </div>
                )}
              </section>

              <KpiStrip resumen={resumen} />

              <div className="tab-row tab-row-1">
                <DayRecapPanel
                  totalGlobal={currentData.totalGlobal}
                  zonasGondola={currentData.zonasGondola}
                  conteoZonas={currentData.conteoZonas}
                />
              </div>
            </div>

            <div className="tab-panel" hidden={tab !== 'video'}>
              <div className="tab-row tab-row-2">
                <section id="video" className="panel" data-tour="video-analizado">
                  <div className="panel-head">
                    <h3>Video analizado</h3>
                  </div>
                  <VideoPanel
                    videoUrl={currentData.videoAnotadoUrl}
                    zonasUrl={currentData.zonasPropuestasUrl}
                    embebido
                    onTimeUpdate={setVideoTime}
                  />
                </section>

                <section id="mapa-calor" className="panel" data-tour="heatmap">
                  <div className="panel-head"><h3>Mapa de calor de flujo</h3></div>
                  <HeatmapPanel heatmapUrl={currentData.heatmapUrl} />
                </section>
              </div>

              <div className="tab-row tab-row-2-wide">
                <section id="mapa-tienda" className="panel" data-tour="store-map">
                  <StoreMapPanel
                    zonasData={currentData.zonasPropuestas}
                    conteoZonas={currentData.conteoZonas}
                    tracking={currentData.tracking}
                    currentTimeSec={videoTime}
                  />
                </section>

                <section id="red-tienda" className="panel" data-tour="network">
                  <NetworkPanel />
                </section>
              </div>
            </div>

            <div className="tab-panel" hidden={tab !== 'rendimiento'}>
              <div className="tab-row tab-row-2-wide" id="estado-gondola">
                <FunnelPanel
                  total={currentData.totalGlobal}
                  zonas={currentData.zonasGondola}
                  zonaSeleccionada={zonaSeleccionada}
                  onSeleccionar={setZonaSeleccionada}
                />

                <PerformanceTable
                  zonas={currentData.zonasGondola}
                  zonaSeleccionada={zonaSeleccionada}
                  onSeleccionar={setZonaSeleccionada}
                />
              </div>

              <div className="tab-row tab-row-2-wide">
                <section id="recomendaciones" className="panel" data-tour="recommendations">
                  <div className="panel-head"><h3>Recomendaciones</h3></div>
                  <div className="panel-body">
                    <AlertsPanel
                      alertas={currentData.alertas}
                      recomendaciones={recomendaciones ?? currentData.recomendaciones}
                      fuente={fuenteReco ?? currentData.recomendacionesFuente}
                    />
                  </div>
                </section>

                <InteractionRateChart
                  zonas={currentData.zonasGondola}
                  multiprocessingUsed={multiprocessingUsed}
                  sparkMetricas={sparkMetricas}
                />
              </div>

            </div>

            <div className="tab-panel" hidden={tab !== 'detalle'}>
              <div className="tab-row tab-row-2" id="embudo-gondola">
                <section className="panel" data-tour="zone-detail">
                  <div className="panel-head"><h3>Detalle por góndola</h3></div>
                  <div className="panel-body">
                    <ZoneShelfPanel zonasGondola={currentData.zonasGondola} />
                  </div>
                </section>

                <section className="panel" data-tour="zone-funnel">
                  <div className="panel-head">
                    <h3>Embudo detallado</h3>
                  </div>
                  <div className="panel-body">
                    <ZoneFunnelTable zonasGondola={currentData.zonasGondola} />
                    {currentData.analisisId && (
                      <div className="mt-4">
                        <ReportDownloads analisisId={currentData.analisisId} />
                      </div>
                    )}
                  </div>
                </section>
              </div>
            </div>

            <div className="tab-panel" hidden={tab !== 'historial'}>
              <div className="tab-row tab-row-1">
                <HistoryPanel
                  recargar={historialKey}
                  onAbrir={(detalle, id) => {
                    updateFromAnalysis({ ...detalle, analisis_id: id }, Date.now());
                    setAnalysisCompleted(true);
                    setMultiprocessingUsed(false);
                    setAnalysisMessage(`Mostrando análisis de ${detalle?.video ?? id}.`);
                    setTab('cargar');
                  }}
                />
              </div>
            </div>
          </div>
        </div>
      </main>
      </div>
      <ProductTour
        isOpen={tourOpen}
        onClose={() => setTourOpen(false)}
        onNavigate={(step) => {
          setVista('tablero');
          if (step?.tab) setTab(step.tab);
        }}
      />
    </div>
  );
}