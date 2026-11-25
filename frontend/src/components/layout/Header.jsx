import { Boxes, CircleHelp } from 'lucide-react';
import logoGondHawk from '../../assets/gondhawk-logo.png';

/**
 * Cabecera del tablero.
 *
 * Reemplaza la antigua barra lateral: la marca, el acceso a la Escena 3D y
 * el recorrido guiado viven aquí.
 */
export function Header({ vista, onToggleVista, onOpenTour }) {
  return (
    <header className="topbar">
      <div className="topbar-inner">
        <div className="brand" data-tour="welcome">
          <span className="brand-mark">
            <img src={logoGondHawk} alt="GondHawk" />
          </span>
          <div>
            <p className="brand-name">GondHawk</p>
            <p className="brand-tagline">Convierte video en decisiones de space management</p>
          </div>
        </div>

        <div className="topbar-actions">
          <button
            type="button"
            className={`ghost-button ${vista === 'sintetico' ? 'active' : ''}`}
            onClick={onToggleVista}
          >
            <Boxes size={14} />
            {vista === 'sintetico' ? 'Volver al tablero' : 'Escena 3D'}
          </button>

          <button type="button" className="ghost-button" onClick={onOpenTour} aria-label="Ver recorrido guiado">
            <CircleHelp size={14} />
            Ver tour
          </button>
        </div>
      </div>
    </header>
  );
}
