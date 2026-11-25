"""
time_analysis.py
Analisis temporal del modulo de Tracking de GondHawk.

Lee el JSONL generado por run_tracking.py y permite analizar
la cantidad de personas identificadas por franjas temporales.

Importante:
    timestamp_ms representa el tiempo transcurrido desde el inicio
    del video. No representa necesariamente una hora real del dia.

Ejemplo:

python tracking/src/time_analysis.py \
    --input tracking/output/tracking.jsonl \
    --interval 5
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def load_tracking(path: Path) -> list[dict[str, Any]]:
    """Carga los registros de tracking desde un archivo JSONL."""

    if not path.exists():
        raise FileNotFoundError(f"No existe el archivo: {path}")

    records = []

    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue

            records.append(json.loads(line))

    return records


def analyze_by_interval(
    records: list[dict[str, Any]],
    interval_seconds: float,
) -> dict[str, Any]:
    """
    Cuenta personas unicas observadas dentro de cada intervalo temporal.

    Una persona cuenta una sola vez dentro de cada intervalo aunque
    aparezca en muchos frames.
    """

    if interval_seconds <= 0:
        raise ValueError("interval_seconds debe ser mayor que 0")

    intervals: dict[int, set[int]] = defaultdict(set)

    first_seen: dict[int, float] = {}
    last_seen: dict[int, float] = {}

    for record in records:
        timestamp_ms = float(record.get("timestamp_ms", 0.0))
        timestamp_seconds = timestamp_ms / 1000.0

        interval_index = int(timestamp_seconds // interval_seconds)

        for track in record.get("tracks", []):
            person_id = int(track["person_id"])

            intervals[interval_index].add(person_id)

            if person_id not in first_seen:
                first_seen[person_id] = timestamp_seconds

            last_seen[person_id] = timestamp_seconds

    interval_results = []

    for index in sorted(intervals):
        start = index * interval_seconds
        end = start + interval_seconds
        people = sorted(intervals[index])

        interval_results.append(
            {
                "inicio_seg": round(start, 2),
                "fin_seg": round(end, 2),
                "personas_unicas": len(people),
                "person_ids": people,
            }
        )

    busiest = None

    if interval_results:
        busiest = max(
            interval_results,
            key=lambda item: item["personas_unicas"],
        )

    return {
        "total_personas_unicas": len(first_seen),
        "intervalo_segundos": interval_seconds,
        "intervalos": interval_results,
        "franja_mayor_visitas": busiest,
        "personas": {
            str(person_id): {
                "primera_aparicion_seg": round(first_seen[person_id], 2),
                "ultima_aparicion_seg": round(last_seen[person_id], 2),
            }
            for person_id in sorted(first_seen)
        },
    }


def print_report(result: dict[str, Any]) -> None:
    """Muestra un resumen legible del analisis."""

    print()
    print("========== ANALISIS TEMPORAL ==========")
    print(f"Personas únicas: {result['total_personas_unicas']}")
    print(f"Intervalo: {result['intervalo_segundos']} segundos")
    print()

    for interval in result["intervalos"]:
        print(
            f"[{interval['inicio_seg']:.1f}s - "
            f"{interval['fin_seg']:.1f}s] "
            f"personas únicas: {interval['personas_unicas']} "
            f"IDs: {interval['person_ids']}"
        )

    busiest = result["franja_mayor_visitas"]

    if busiest:
        print()
        print(
            "Franja con más visitas: "
            f"{busiest['inicio_seg']:.1f}s - "
            f"{busiest['fin_seg']:.1f}s "
            f"({busiest['personas_unicas']} personas)"
        )

    print("========================================")
    print()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analisis temporal del tracking de GondHawk"
    )

    parser.add_argument(
        "--input",
        required=True,
        help="JSONL generado por run_tracking.py",
    )

    parser.add_argument(
        "--interval",
        type=float,
        default=5.0,
        help="Tamaño de la franja temporal en segundos",
    )

    parser.add_argument(
        "--output",
        default=None,
        help="Archivo JSON opcional para guardar el analisis",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    input_path = Path(args.input)

    records = load_tracking(input_path)

    result = analyze_by_interval(
        records,
        interval_seconds=args.interval,
    )

    print_report(result)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        output_path.write_text(
            json.dumps(
                result,
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        print(f"[ok] Analisis guardado en: {output_path}")


if __name__ == "__main__":
    main()
