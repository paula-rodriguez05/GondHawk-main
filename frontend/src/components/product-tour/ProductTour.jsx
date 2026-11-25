import { useCallback, useEffect, useMemo, useState } from 'react';
import { X } from 'lucide-react';
import { TOUR_STEPS } from './tourSteps';
import './ProductTour.css';

const TOOLTIP_MARGIN = 12;
const TARGET_PADDING = 8;

function targetExists(step) {
  return !step.target || document.querySelector(step.target);
}

function findAvailableStep(startIndex, direction) {
  let index = startIndex;

  while (index >= 0 && index < TOUR_STEPS.length) {
    if (targetExists(TOUR_STEPS[index])) return index;
    index += direction;
  }

  return null;
}

function getTooltipPosition(rect) {
  if (!rect) {
    return {
      left: '50%',
      top: '50%',
      transform: 'translate(-50%, -50%)',
    };
  }

  const viewportWidth = window.innerWidth;
  const viewportHeight = window.innerHeight;
  const tooltipWidth = Math.min(360, viewportWidth - 24);
  const estimatedHeight = 230;
  const left = Math.min(
    Math.max(rect.left + rect.width / 2 - tooltipWidth / 2, TOOLTIP_MARGIN),
    viewportWidth - tooltipWidth - TOOLTIP_MARGIN,
  );
  const fitsBelow = rect.bottom + TOOLTIP_MARGIN + estimatedHeight <= viewportHeight;
  const top = fitsBelow
    ? rect.bottom + TOOLTIP_MARGIN
    : Math.max(TOOLTIP_MARGIN, rect.top - estimatedHeight - TOOLTIP_MARGIN);

  return { left, top, width: tooltipWidth };
}

export function ProductTour({ isOpen, onClose, onNavigate }) {
  const [currentIndex, setCurrentIndex] = useState(0);
  const [targetRect, setTargetRect] = useState(null);
  const currentStep = TOUR_STEPS[currentIndex];

  const updateTargetRect = useCallback(() => {
    if (!currentStep?.target) {
      setTargetRect(null);
      return;
    }

    const target = document.querySelector(currentStep.target);
    if (!target) {
      setTargetRect(null);
      return;
    }

    const rect = target.getBoundingClientRect();
    setTargetRect({
      top: rect.top - TARGET_PADDING,
      left: rect.left - TARGET_PADDING,
      width: rect.width + TARGET_PADDING * 2,
      height: rect.height + TARGET_PADDING * 2,
      bottom: rect.bottom + TARGET_PADDING,
    });
  }, [currentStep]);

  useEffect(() => {
    if (!isOpen) return undefined;

    const firstStep = findAvailableStep(0, 1) ?? 0;
    const frameId = window.requestAnimationFrame(() => setCurrentIndex(firstStep));

    return () => window.cancelAnimationFrame(frameId);
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) return undefined;

    // El objetivo de este paso puede vivir en otra pestaña del tablero: las
    // pestañas inactivas se ocultan con `hidden`, así que primero hay que
    // activar la que corresponde. Sin esto, el target existe en el DOM pero
    // mide 0x0 (display: none) y el resaltado aparece en la esquina.
    onNavigate?.(currentStep);

    const frameId = window.requestAnimationFrame(updateTargetRect);
    const delayedFrameId = window.setTimeout(updateTargetRect, 350);

    window.addEventListener('resize', updateTargetRect);
    window.addEventListener('scroll', updateTargetRect, true);

    return () => {
      window.cancelAnimationFrame(frameId);
      window.clearTimeout(delayedFrameId);
      window.removeEventListener('resize', updateTargetRect);
      window.removeEventListener('scroll', updateTargetRect, true);
    };
  }, [currentStep, isOpen, updateTargetRect]);

  useEffect(() => {
    if (!isOpen) return undefined;

    const handleKeyDown = (event) => {
      if (event.key === 'Escape') onClose();
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  const availableCount = TOUR_STEPS.filter((step) => targetExists(step)).length;

  const visiblePosition = useMemo(() => {
    let position = 0;
    for (let index = 0; index <= currentIndex; index += 1) {
      if (targetExists(TOUR_STEPS[index])) position += 1;
    }
    return position;
  }, [currentIndex]);

  if (!isOpen || !currentStep) return null;

  const nextIndex = findAvailableStep(currentIndex + 1, 1);
  const previousIndex = findAvailableStep(currentIndex - 1, -1);
  const isLastStep = nextIndex === null;
  const tooltipStyle = getTooltipPosition(targetRect);

  return (
    <div className="product-tour" role="dialog" aria-modal="true" aria-label="Recorrido guiado de GondHawk">
      <div className="product-tour-backdrop" aria-hidden="true" />

      {targetRect && (
        <div
          className="product-tour-spotlight"
          style={{
            top: targetRect.top,
            left: targetRect.left,
            width: targetRect.width,
            height: targetRect.height,
          }}
          aria-hidden="true"
        />
      )}

      <div className="product-tour-tooltip" style={tooltipStyle}>
        <div className="product-tour-heading">
          <div>
            <p className="product-tour-progress">Paso {visiblePosition} de {availableCount}</p>
            <h2 className="product-tour-title">{currentStep.title}</h2>
          </div>
          <button type="button" className="product-tour-close" onClick={onClose} aria-label="Cerrar tour">
            <X size={18} />
          </button>
        </div>

        <p className="product-tour-content">{currentStep.content}</p>

        <div className="product-tour-actions">
          <button
            type="button"
            className="product-tour-button product-tour-button-secondary"
            onClick={() => previousIndex !== null && setCurrentIndex(previousIndex)}
            disabled={previousIndex === null}
          >
            Anterior
          </button>
          <button
            type="button"
            className="product-tour-button product-tour-button-primary"
            onClick={() => (isLastStep ? onClose() : setCurrentIndex(nextIndex))}
          >
            {isLastStep ? 'Finalizar' : 'Siguiente'}
          </button>
        </div>
      </div>
    </div>
  );
}
