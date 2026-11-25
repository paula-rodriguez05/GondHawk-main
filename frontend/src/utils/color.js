export function temperaturaAColor(temperatura, tasaRechazo) {
  if (temperatura === 'caliente') return 'var(--hot)';
  if (temperatura === 'fria' || temperatura === 'fría') return 'var(--cold)';
  if (temperatura === 'media' || temperatura === 'templada') return 'var(--warning)';
  if (typeof tasaRechazo === 'number') {
    return tasaRechazo > 0.5 ? 'var(--hot)' : tasaRechazo < 0.2 ? 'var(--cold)' : 'var(--warning)';
  }
  return 'var(--warning)';
}

export function temperaturaLabel(temperatura) {
  if (temperatura === 'caliente') return 'Caliente';
  if (temperatura === 'fria' || temperatura === 'fría') return 'Fría';
  return 'Templada';
}

export const ZONE_LABELS = {
  gondola_A1: 'Góndola A1', gondola_A2: 'Góndola A2', gondola_A3: 'Góndola A3',
  gondola_B1: 'Góndola B1', pasillo_central: 'Pasillo central',
};
export const zoneLabel = (zoneId) => ZONE_LABELS[zoneId] ?? zoneId;