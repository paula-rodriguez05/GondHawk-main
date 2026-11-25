import { copyFileSync, mkdirSync, existsSync } from 'node:fs';
import { join, resolve } from 'node:path';

const ROOT = process.cwd();
const ORIGEN = resolve(ROOT, '..', 'backend', 'pipeline', 'output');
const DESTINO = resolve(ROOT, 'public', 'data');
const ARCHIVOS = [
  'metricas_interaccion.json',
  'metricas_pipeline.json',
  'conteo_zonas.json',
  'detecciones.meta.json',
  'heatmap.png',
];

mkdirSync(DESTINO, { recursive: true });
for (const archivo of ARCHIVOS) {
  const origen = join(ORIGEN, archivo);
  if (existsSync(origen)) {
    copyFileSync(origen, join(DESTINO, archivo));
    console.log(`copiado ${archivo}`);
  } else {
    console.warn(`falta ${archivo} — ¿ya corrió el pipeline en backend/pipeline/?`);
  }
}