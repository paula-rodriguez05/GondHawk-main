import { useState } from 'react';
import { DATA_SOURCES } from '../../config/dataConfig';

const FORMATOS = [
  { id: 'pdf', label: 'PDF', hint: 'Informe ejecutivo' },
  { id: 'excel', label: 'Excel', hint: 'Datos por zona y evento' },
  { id: 'word', label: 'Word', hint: 'Informe editable' },
];

/**
 * Descarga de reportes. Los genera el backend bajo demanda.
 *
 * El error se muestra en pantalla en vez de fallar en silencio porque la causa
 * más común es una dependencia sin instalar (reportlab, openpyxl, python-docx)
 * y ese mensaje dice exactamente qué falta.
 */
export function ReportDownloads({ analisisId }) {
  const [error, setError] = useState(null);
  const [descargando, setDescargando] = useState(null);

  if (!analisisId) return null;

  const descargar = async (formato) => {
    setError(null);
    setDescargando(formato);
    try {
      const res = await fetch(DATA_SOURCES.reporte(analisisId, formato));
      if (!res.ok) {
        const cuerpo = await res.json().catch(() => ({}));
        throw new Error(cuerpo.detail ?? `No se pudo generar el reporte ${formato}.`);
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const enlace = document.createElement('a');
      enlace.href = url;
      enlace.download = `reporte_gondhawk.${formato === 'excel' ? 'xlsx' : formato === 'word' ? 'docx' : 'pdf'}`;
      document.body.appendChild(enlace);
      enlace.click();
      enlace.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error al descargar.');
    } finally {
      setDescargando(null);
    }
  };

  return (
    <div className="rounded-2xl border border-[var(--panel-border)] bg-[var(--panel)] p-4" data-tour="reports">
      <p className="text-sm text-[var(--ink-muted)]">Descargar análisis</p>
      <div className="mt-3 flex flex-wrap gap-2">
        {FORMATOS.map((f) => (
          <button
            key={f.id}
            type="button"
            onClick={() => descargar(f.id)}
            disabled={descargando !== null}
            className="rounded-xl border border-[var(--panel-border)] px-4 py-2 text-left text-base hover:border-[var(--accent)] disabled:opacity-50"
          >
            <span className="block">{descargando === f.id ? 'Generando...' : f.label}</span>
            <span className="block text-[13px] text-[var(--ink-muted)]">{f.hint}</span>
          </button>
        ))}
      </div>
      {error && <p className="mt-3 text-sm text-red-400">{error}</p>}
    </div>
  );
}
