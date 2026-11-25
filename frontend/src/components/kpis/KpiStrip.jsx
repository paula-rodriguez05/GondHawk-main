import { Users, Clock, Hand, RotateCcw } from 'lucide-react';

const ICONOS = { personas: Users, permanencia: Clock, interaccion: Hand, rechazo: RotateCcw };

/**
 * Tira de KPIs principales.
 *
 * A diferencia del mockup, no se muestran variaciones "vs. período anterior":
 * el sistema analiza un video a la vez y no tiene serie histórica comparable,
 * así que ese porcentaje sería inventado. Cuando el historial acumule análisis
 * del mismo local, se puede calcular de verdad.
 */
export function KpiStrip({ resumen }) {
  const items = [
    { id: 'personas', label: 'Personas detectadas', valor: resumen.totalPersonasAprox },
    { id: 'permanencia', label: 'Permanencia media', valor: `${resumen.dwellPromedioGlobal.toFixed(0)} s` },
    { id: 'interaccion', label: 'Tasa de interacción', valor: `${Math.round((resumen.tasaInteraccionGlobal ?? 0) * 100)} %` },
    { id: 'rechazo', label: 'Tasa de rechazo', valor: `${Math.round((resumen.tasaRechazoGlobal ?? 0) * 100)} %` },
  ];

  return (
    <div className="kpi-grid" data-tour="metrics">
      {items.map((item) => {
        const Icono = ICONOS[item.id];
        return (
          <div key={item.id} className="kpi-card">
            <div className="kpi-icon"><Icono size={20} /></div>
            <div>
              <p className="kpi-label">{item.label}</p>
              <p className="kpi-value">{item.valor}</p>
            </div>
          </div>
        );
      })}
    </div>
  );
}
