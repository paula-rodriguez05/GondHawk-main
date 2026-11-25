"""
evaluar_exactitud.py
Medicion de exactitud del detector de eventos — Modulo 1, GondHawk.

El reto evalua "exactitud en la deteccion de eventos", asi que hace falta un
numero, no una impresion. Este script compara los eventos detectados contra el
ground truth que genera `simular_tracking.py` y reporta precision, recall y F1
por tipo de evento.

El emparejamiento es por (track_id, zone_id, event_type) tratado como
multiconjunto: no se exige que el instante coincida, solo que la secuencia de
lo que hizo cada persona en cada zona sea la correcta. Es el nivel de
exactitud que le importa al negocio (cuantas tomas y cuantas devoluciones
hubo), no la precision al frame.

Uso:
    python deteccion_eventos/tools/evaluar_exactitud.py \\
        --eventos deteccion_eventos/output/eventos_interaccion.jsonl \\
        --ground-truth deteccion_eventos/output/tracking_sintetico_ground_truth.json
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def cargar_detectados(ruta: Path) -> Counter:
    contador: Counter = Counter()
    with ruta.open("r", encoding="utf-8") as fh:
        for linea in fh:
            linea = linea.strip()
            if not linea:
                continue
            evento = json.loads(linea)
            contador[
                (
                    str(evento["track_id"]),
                    str(evento["zone_id"]),
                    evento["event_type"],
                )
            ] += 1
    return contador


def cargar_esperados(ruta: Path) -> Counter:
    data = json.loads(ruta.read_text(encoding="utf-8"))
    contador: Counter = Counter()
    for persona in data["personas"]:
        for esperado in persona["eventos_esperados"]:
            contador[
                (
                    persona["track_id"],
                    str(esperado["zone_id"]),
                    esperado["event_type"],
                )
            ] += 1
    return contador


def evaluar(detectados: Counter, esperados: Counter) -> dict:
    tipos = sorted({k[2] for k in detectados} | {k[2] for k in esperados})
    filas = []

    tp_total = fp_total = fn_total = 0

    for tipo in tipos:
        tp = fp = fn = 0
        claves = {k for k in detectados if k[2] == tipo} | {
            k for k in esperados if k[2] == tipo
        }
        for clave in claves:
            d = detectados.get(clave, 0)
            e = esperados.get(clave, 0)
            tp += min(d, e)
            fp += max(0, d - e)
            fn += max(0, e - d)

        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = (
            2 * precision * recall / (precision + recall)
            if (precision + recall)
            else 0.0
        )

        filas.append(
            {
                "event_type": tipo,
                "esperados": tp + fn,
                "detectados": tp + fp,
                "aciertos": tp,
                "falsos_positivos": fp,
                "falsos_negativos": fn,
                "precision": round(precision, 4),
                "recall": round(recall, 4),
                "f1": round(f1, 4),
            }
        )
        tp_total += tp
        fp_total += fp
        fn_total += fn

    p_global = tp_total / (tp_total + fp_total) if (tp_total + fp_total) else 0.0
    r_global = tp_total / (tp_total + fn_total) if (tp_total + fn_total) else 0.0
    f_global = (
        2 * p_global * r_global / (p_global + r_global) if (p_global + r_global) else 0.0
    )

    return {
        "por_tipo": filas,
        "global": {
            "precision": round(p_global, 4),
            "recall": round(r_global, 4),
            "f1": round(f_global, 4),
            "aciertos": tp_total,
            "falsos_positivos": fp_total,
            "falsos_negativos": fn_total,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Exactitud del detector de eventos")
    parser.add_argument("--eventos", required=True)
    parser.add_argument("--ground-truth", required=True)
    parser.add_argument("--salida", default=None, help="JSON opcional con el reporte")
    args = parser.parse_args()

    detectados = cargar_detectados(Path(args.eventos))
    esperados = cargar_esperados(Path(args.ground_truth))
    reporte = evaluar(detectados, esperados)

    encabezado = f"{'evento':<12}{'esper':>7}{'detec':>7}{'ok':>6}{'FP':>5}{'FN':>5}{'prec':>8}{'rec':>8}{'F1':>8}"
    print(encabezado)
    print("-" * len(encabezado))
    for fila in reporte["por_tipo"]:
        print(
            f"{fila['event_type']:<12}{fila['esperados']:>7}{fila['detectados']:>7}"
            f"{fila['aciertos']:>6}{fila['falsos_positivos']:>5}{fila['falsos_negativos']:>5}"
            f"{fila['precision']:>8.2f}{fila['recall']:>8.2f}{fila['f1']:>8.2f}"
        )
    g = reporte["global"]
    print("-" * len(encabezado))
    print(
        f"{'GLOBAL':<12}{'':>7}{'':>7}{g['aciertos']:>6}{g['falsos_positivos']:>5}"
        f"{g['falsos_negativos']:>5}{g['precision']:>8.2f}{g['recall']:>8.2f}{g['f1']:>8.2f}"
    )

    if args.salida:
        Path(args.salida).write_text(
            json.dumps(reporte, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\n[ok] Reporte: {args.salida}")


if __name__ == "__main__":
    main()
