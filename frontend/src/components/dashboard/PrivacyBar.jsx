import { ShieldCheck, EyeOff, Cpu, Fingerprint, ScanFace, FileCheck } from 'lucide-react';

const GARANTIAS = [
  { icono: ScanFace, texto: 'Sin reconocimiento facial' },
  { icono: EyeOff, texto: 'Sin almacenamiento de imágenes' },
  { icono: Cpu, texto: 'Procesamiento local' },
  { icono: Fingerprint, texto: 'IDs anónimos temporales' },
  { icono: FileCheck, texto: 'Cumple Ley 1581 de 2012' },
];

export function PrivacyBar() {
  return (
    <section className="panel privacy-panel" data-tour="privacy">
      <div className="panel-head"><h3>Privacidad por diseño</h3></div>
      <ul className="privacy-grid">
        {GARANTIAS.map(({ icono: Icono, texto }) => (
          <li key={texto}><Icono size={14} />{texto}</li>
        ))}
      </ul>
      <div className="privacy-seal">
        <ShieldCheck size={18} />
        <span>Los rostros se difuminan antes de guardar cualquier imagen.</span>
      </div>
    </section>
  );
}
