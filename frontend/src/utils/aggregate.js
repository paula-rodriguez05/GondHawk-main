export function resumenGlobal(totalGlobal, zonasGondola = []) {
  const totalPersonasAprox = zonasGondola.reduce((a, z) => a + (z.personas_unicas ?? 0), 0);

  const dwellPonderado = zonasGondola.reduce(
    (a, z) => a + (z.dwell_promedio_s ?? 0) * (z.personas_unicas ?? 0), 0
  );

  return {
    totalPersonasAprox,
    dwellPromedioGlobal: totalPersonasAprox > 0 ? dwellPonderado / totalPersonasAprox : 0,
    tasaInteraccionGlobal: totalGlobal.tasa_interaccion,
    tasaRechazoGlobal: totalGlobal.tasa_rechazo,
  };
}