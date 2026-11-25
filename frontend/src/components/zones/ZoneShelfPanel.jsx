import { Users, Clock } from 'lucide-react';
import { temperaturaAColor, temperaturaLabel, zoneLabel } from '../../utils/color';

export function ZoneShelfPanel({ zonasGondola }) {
  return (
    <div className="rounded-2xl border border-[var(--panel-border)] bg-[var(--panel)] p-4">
      <p className="mb-3 text-base text-[var(--ink-muted)]">Estado por góndola</p>
      <div className="grid gap-3" style={{ gridTemplateColumns: `repeat(${zonasGondola.length}, minmax(0, 1fr))` }}>
        {zonasGondola.map((zona) => {
          const color = temperaturaAColor(zona.temperatura, zona.tasa_rechazo);
          return (
            <div key={zona.zone_id} className="rounded-xl border border-[var(--panel-border)] p-3">
              <p className="text-base">{zoneLabel(zona.zone_id)}</p>
              <div className="mt-3 flex h-20 items-center justify-center rounded-lg border border-[var(--panel-border)]">
                <Users size={26} style={{ color }} />
              </div>
              <div className="mt-2 flex items-center justify-between gap-2 text-sm text-[var(--ink-muted)]">
                <span className="temperature-badge" style={{ color, borderColor: color }}>
                  {temperaturaLabel(zona.temperatura)}
                </span>
                <span className="flex items-center gap-1"><Clock size={12} /> {(zona.dwell_promedio_s ?? 0).toFixed(1)}s</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}