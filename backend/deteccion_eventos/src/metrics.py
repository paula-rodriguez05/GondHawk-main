"""
metrics.py
Embudo de interaccion y metricas accionables — Modulo 1, GondHawk.

Convierte la lista de eventos en el tablero que consumen el modulo 6
(pipeline, Laura) y el modulo 7 (dashboard):

    visitas -> se detiene -> interactua -> devuelve / se lleva

Tambien cruza con `dwell_time.jsonl` del modulo 5 (Diego) cuando esta
disponible, para reportar el dwell medido por el, no el nuestro, y detectar
discrepancias entre los dos modulos antes de la demo.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from state_machine import (
    EVENTO_APPROACH,
    EVENTO_PASS_BY,
    EVENTO_PICKUP,
    EVENTO_RETURN,
    EVENTO_TAKEAWAY,
    Evento,
)


class DwellIndex:
    """
    Indice de los eventos de permanencia del modulo 5.

    Formato de entrada (una linea por episodio de permanencia):
        {"track_id": "3", "zone_id": "gondola_A3", "dwell_time_s": 14.2,
         "timestamp_ms": 4733.4, "detuvo": true}

    `timestamp_ms` es el instante de ENTRADA a la zona (documentado en el
    README del modulo 5), asi que buscamos el episodio cuyo intervalo
    [entrada, entrada + dwell] contiene el timestamp del evento.
    """

    def __init__(self, registros: Iterable[dict[str, Any]] | None = None):
        self._por_clave: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for registro in registros or []:
            clave = (str(registro.get("track_id")), str(registro.get("zone_id")))
            self._por_clave.setdefault(clave, []).append(registro)
        for lista in self._por_clave.values():
            lista.sort(key=lambda r: float(r.get("timestamp_ms", 0.0)))

    @classmethod
    def desde_archivo(cls, ruta: Path | str | None) -> "DwellIndex":
        if ruta is None:
            return cls()
        ruta = Path(ruta)
        if not ruta.exists():
            raise FileNotFoundError(f"No existe el archivo de dwell: {ruta}")

        registros = []
        with ruta.open("r", encoding="utf-8") as fh:
            for linea in fh:
                linea = linea.strip()
                if linea:
                    registros.append(json.loads(linea))
        return cls(registros)

    def __len__(self) -> int:
        return sum(len(v) for v in self._por_clave.values())

    def buscar(
        self, track_id: str, zone_id: str, timestamp_ms: float
    ) -> dict[str, Any] | None:
        """Episodio de permanencia que cubre ese instante, si existe."""
        candidatos = self._por_clave.get((str(track_id), str(zone_id)))
        if not candidatos:
            return None

        mejor = None
        mejor_dist = float("inf")
        for registro in candidatos:
            inicio = float(registro.get("timestamp_ms", 0.0))
            fin = inicio + float(registro.get("dwell_time_s", 0.0)) * 1000.0
            if inicio <= timestamp_ms <= fin:
                return registro
            dist = min(abs(timestamp_ms - inicio), abs(timestamp_ms - fin))
            if dist < mejor_dist:
                mejor, mejor_dist = registro, dist

        # Tolerancia de 1 s: el modulo 5 fragmenta episodios cuando el tracker
        # pierde el ID un frame, y nuestra ventana de gracia no. Sin esta
        # tolerancia perderiamos el cruce justo en las visitas con oclusion.
        return mejor if mejor_dist <= 1000.0 else None


def _tasa(numerador: int, denominador: int) -> float:
    return round(numerador / denominador, 4) if denominador else 0.0


def calcular_metricas(
    eventos: list[Evento],
    zone_ids: Iterable[str],
    umbral_zona_fria: float = 0.15,
) -> dict[str, Any]:
    """
    Calcula el embudo por zona y las metricas de space management.

    `umbral_zona_fria`: por debajo de esta tasa de interaccion, la zona se
    marca como fria (candidata a reubicacion de producto).
    """
    por_zona: dict[str, dict[str, Any]] = {
        zone_id: {
            "zone_id": zone_id,
            "visitas": 0,
            "pass_by": 0,
            "approach": 0,
            "pickup": 0,
            "return": 0,
            "takeaway": 0,
            "personas_unicas": set(),
            "_dwell_total": 0.0,
            "_dwell_n": 0,
        }
        for zone_id in zone_ids
    }

    for evento in eventos:
        fila = por_zona.setdefault(
            evento.zone_id,
            {
                "zone_id": evento.zone_id,
                "visitas": 0,
                "pass_by": 0,
                "approach": 0,
                "pickup": 0,
                "return": 0,
                "takeaway": 0,
                "personas_unicas": set(),
                "_dwell_total": 0.0,
                "_dwell_n": 0,
            },
        )
        fila["personas_unicas"].add(evento.track_id)

        if evento.event_type in (EVENTO_APPROACH, EVENTO_PASS_BY):
            fila["visitas"] += 1  # toda visita empieza en uno de los dos
        if evento.event_type == EVENTO_APPROACH:
            fila["approach"] += 1
        elif evento.event_type == EVENTO_PASS_BY:
            fila["pass_by"] += 1
        elif evento.event_type == EVENTO_PICKUP:
            fila["pickup"] += 1
        elif evento.event_type == EVENTO_RETURN:
            fila["return"] += 1
        elif evento.event_type == EVENTO_TAKEAWAY:
            fila["takeaway"] += 1
            fila["_dwell_total"] += evento.dwell_time_s
            fila["_dwell_n"] += 1

        if evento.event_type in (EVENTO_APPROACH, EVENTO_PICKUP):
            fila["_dwell_total"] += evento.dwell_time_s
            fila["_dwell_n"] += 1

    zonas_salida = []
    for zone_id, fila in sorted(por_zona.items()):
        visitas = fila["visitas"]
        approach = fila["approach"]
        pickup = fila["pickup"]
        devoluciones = fila["return"]

        tasa_interaccion = _tasa(pickup, approach)
        tasa_rechazo = _tasa(devoluciones, pickup)

        if visitas == 0:
            temperatura = "sin_datos"
        elif tasa_interaccion >= 0.5 and approach >= 3:
            temperatura = "caliente"
        elif tasa_interaccion < umbral_zona_fria:
            temperatura = "fria"
        else:
            temperatura = "templada"

        zonas_salida.append(
            {
                "zone_id": zone_id,
                "personas_unicas": len(fila["personas_unicas"]),
                "embudo": {
                    "visitas": visitas,
                    "pasa_de_largo": fila["pass_by"],
                    "se_detiene": approach,
                    "toma_producto": pickup,
                    "devuelve": devoluciones,
                    "se_lo_lleva": fila["takeaway"],
                },
                "tasa_detencion": _tasa(approach, visitas),
                "tasa_interaccion": tasa_interaccion,
                "tasa_rechazo": tasa_rechazo,
                "tasa_conversion": _tasa(fila["takeaway"], pickup),
                "dwell_promedio_s": (
                    round(fila["_dwell_total"] / fila["_dwell_n"], 2)
                    if fila["_dwell_n"]
                    else 0.0
                ),
                "temperatura": temperatura,
            }
        )

    total = {
        "visitas": sum(z["embudo"]["visitas"] for z in zonas_salida),
        "se_detiene": sum(z["embudo"]["se_detiene"] for z in zonas_salida),
        "toma_producto": sum(z["embudo"]["toma_producto"] for z in zonas_salida),
        "devuelve": sum(z["embudo"]["devuelve"] for z in zonas_salida),
        "se_lo_lleva": sum(z["embudo"]["se_lo_lleva"] for z in zonas_salida),
    }
    total["tasa_interaccion"] = _tasa(total["toma_producto"], total["se_detiene"])
    total["tasa_rechazo"] = _tasa(total["devuelve"], total["toma_producto"])

    return {
        "total": total,
        "zonas": zonas_salida,
        "alertas": _generar_alertas(zonas_salida),
    }


def _generar_alertas(zonas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Senales accionables para space management. Son observaciones sobre los
    datos, no recomendaciones de negocio: el motor de recomendacion es un
    entregable aparte del reto.
    """
    alertas = []
    for zona in zonas:
        embudo = zona["embudo"]
        if zona["temperatura"] == "fria" and embudo["visitas"] >= 3:
            alertas.append(
                {
                    "zone_id": zona["zone_id"],
                    "tipo": "zona_fria",
                    "mensaje": (
                        f"{embudo['visitas']} visitas y solo "
                        f"{embudo['toma_producto']} interacciones: hay trafico "
                        "pero el producto no engancha."
                    ),
                }
            )
        if zona["tasa_rechazo"] >= 0.5 and embudo["toma_producto"] >= 2:
            alertas.append(
                {
                    "zone_id": zona["zone_id"],
                    "tipo": "rechazo_alto",
                    "mensaje": (
                        f"{embudo['devuelve']} de {embudo['toma_producto']} "
                        "productos tomados vuelven al estante: revisar precio, "
                        "facing o informacion visible."
                    ),
                }
            )
        if embudo["visitas"] >= 3 and zona["tasa_detencion"] <= 0.2:
            alertas.append(
                {
                    "zone_id": zona["zone_id"],
                    "tipo": "trafico_sin_parada",
                    "mensaje": (
                        "La gente pasa pero no se detiene: candidata a cambio "
                        "de planograma o material visual."
                    ),
                }
            )
    return alertas
