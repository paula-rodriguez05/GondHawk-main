import { zoneLabel } from '../../utils/color';

const COLOR_PRIORIDAD = {
  alta: 'text-red-400 border-red-400/40',
  media: 'text-amber-400 border-amber-400/40',
  oportunidad: 'text-emerald-400 border-emerald-400/40',
  informativa: 'text-sky-400 border-sky-400/40',
};

/**
 * Recomendaciones del motor de space management.
 *
 * Acepta dos formas: las recomendaciones ricas del recomendador (con título,
 * detalle, acción y prioridad) y las alertas simples del cálculo de métricas.
 * La etiqueta de fuente se muestra a propósito: quien lea esto tiene que saber
 * si el texto lo redactó un modelo o si viene de las reglas deterministas.
 */
export function AlertsPanel({ alertas, recomendaciones, fuente }) {
  const items = recomendaciones?.length ? recomendaciones : alertas ?? [];

  if (items.length === 0) {
    return <p className="text-base text-[var(--ink-muted)]">Sin recomendaciones para este análisis.</p>;
  }

  const etiquetaFuente = fuente?.startsWith('ia:')
    ? `Redactadas con ${fuente.slice(3)} sobre métricas calculadas localmente`
    : fuente
      ? 'Generadas por el motor de reglas (sin modelo externo)'
      : null;

  return (
    <div className="rounded-2xl border border-[var(--panel-border)] bg-[var(--panel)] p-4">
      {etiquetaFuente && (
        <p className="mb-3 text-[13px] text-[var(--ink-muted)]">{etiquetaFuente}</p>
      )}
      <ul className="space-y-3">
        {items.map((item, i) => (
          <li key={`${item.zone_id}-${i}`} className="rounded-xl border border-[var(--panel-border)] p-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-base font-medium">{zoneLabel(item.zone_id)}</span>
              {item.prioridad && (
                <span className={`rounded-full border px-2 py-0.5 text-[12px] uppercase ${COLOR_PRIORIDAD[item.prioridad] ?? ''}`}>
                  {item.prioridad}
                </span>
              )}
            </div>
            {item.titulo && <p className="mt-1 text-base">{item.titulo}</p>}
            <p className="mt-1 text-sm text-[var(--ink-muted)]">{item.detalle ?? item.mensaje}</p>
            {item.accion && (
              <p className="mt-2 text-sm">
                <span className="text-[var(--ink-muted)]">Acción: </span>
                {item.accion}
              </p>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
