import { Sparkles } from 'lucide-react';
import { generateDayRecap } from '../../utils/dayRecap';

export function DayRecapPanel({ totalGlobal, zonasGondola, conteoZonas }) {
  const bullets = generateDayRecap({ totalGlobal, zonasGondola, conteoZonas });

  return (
    <section className="panel">
      <div className="panel-head">
        <h3><Sparkles size={14} style={{ display: 'inline', marginRight: 6, verticalAlign: '-2px' }} />Resumen del día</h3>
      </div>
      <div className="panel-body">
        {bullets.length === 0 ? (
          <p className="day-recap-empty">El resumen en palabras aparecerá aquí después de analizar un video.</p>
        ) : (
          <ul className="day-recap-list">
            {bullets.map((texto, i) => (
              <li key={i}>{texto}</li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
