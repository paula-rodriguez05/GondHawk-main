export function HeatmapPanel({ heatmapUrl }) {
  return (
    <div className="overflow-hidden rounded-2xl border border-[var(--panel-border)] bg-[var(--panel)]">
      {heatmapUrl ? (
        <img src={heatmapUrl} alt="Mapa de calor de flujo en la tienda" className="h-full w-full object-cover" />
      ) : (
        <div className="flex min-h-48 items-center justify-center p-4 text-base text-[var(--ink-muted)]">
          El mapa de calor aparecerá después del análisis.
        </div>
      )}
    </div>
  );
}