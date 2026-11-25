import { zoneLabel } from '../../utils/color';

export function ZoneFunnelTable({ zonasGondola }) {
  return (
    <div className="rounded-2xl border border-[var(--panel-border)] bg-[var(--panel)] p-4">
      <p className="mb-3 text-base text-[var(--ink-muted)]">Embudo por góndola</p>
      <table className="w-full text-base">
        <thead>
          <tr className="border-b border-[var(--panel-border)] text-left text-[var(--ink-muted)]">
            <th className="py-2 font-normal">Góndola</th>
            <th className="py-2 font-normal">Aproximación</th>
            <th className="py-2 font-normal">Toma</th>
            <th className="py-2 font-normal">Devolución</th>
          </tr>
        </thead>
        <tbody>
          {zonasGondola.map((zona) => {
            const embudo = zona.embudo ?? {};
            return (
              <tr key={zona.zone_id} className="border-b border-[var(--panel-border)] last:border-0">
                <td className="py-2">{zoneLabel(zona.zone_id)}</td>
                <td className="py-2">{embudo.se_detiene ?? 0}</td>
                <td className="py-2">{embudo.toma_producto ?? 0}</td>
                <td className="py-2">{embudo.devuelve ?? 0}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}