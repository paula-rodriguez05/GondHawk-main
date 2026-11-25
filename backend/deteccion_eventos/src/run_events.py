"""
run_events.py
Punto de entrada del Modulo 1 (Deteccion de eventos de interaccion) — GondHawk.

Entradas:
    - tracking/output/tracking.jsonl            (modulo 3, Juan)
    - mapas_de_calor/config/zonas.json          (modulo 4, fuente unica de zonas)
    - tiempo_permanencia/output/dwell_time.jsonl (modulo 5, Diego — opcional)
    - config/productos.json                     (mapa zone_id -> SKU — opcional)

Salidas:
    - output/eventos_interaccion.jsonl  formato canonico, rico (dashboard, pipeline)
    - output/eventos_compliance.jsonl   proyeccion que pasa el validador del modulo 8
    - output/metricas_interaccion.json  embudo por gondola y alertas
    - output/reporte_integracion.json   diagnostico del cruce entre modulos

Ejemplo:

    python deteccion_eventos/src/run_events.py \\
        --tracking tracking/output/tracking.jsonl \\
        --zonas mapas_de_calor/config/zonas.json \\
        --dwell tiempo_permanencia/output/dwell_time.jsonl \\
        --outdir deteccion_eventos/output
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterator

sys.path.insert(0, str(Path(__file__).resolve().parent))

from metrics import DwellIndex, calcular_metricas  # noqa: E402
from reach_detector import ReachConfig  # noqa: E402
from state_machine import (  # noqa: E402
    EVENTOS_COMPLIANCE,
    Evento,
    InteractionConfig,
    InteractionStateMachine,
)
from zonas import cargar_layout  # noqa: E402


def leer_tracking(ruta: Path) -> Iterator[dict[str, Any]]:
    """Lee tracking.jsonl en streaming (no carga el video entero en memoria)."""
    if not ruta.exists():
        raise FileNotFoundError(f"No existe el archivo de tracking: {ruta}")

    with ruta.open("r", encoding="utf-8") as fh:
        for numero, linea in enumerate(fh, start=1):
            linea = linea.strip()
            if not linea:
                continue
            try:
                yield json.loads(linea)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Linea {numero} de {ruta} no es JSON valido: {exc}"
                ) from None


PATRON_SKU = re.compile(r"^SKU_[A-Za-z0-9_]+$")


def cargar_productos(ruta: Path | None) -> dict[str, str]:
    """
    Carga el mapa zone_id -> SKU.

    Dos reglas que existen por errores reales encontrados en el repo:

    - Las zonas sin producto (las de transito, que en el JSON aparecen como
      `null`) se **omiten**. Antes se hacia `str(v)` sobre todos los valores,
      lo que convertia `null` en la cadena "None" y esa cadena terminaba
      escrita como `product_id` en la salida de cumplimiento, donde falla la
      validacion.
    - Los SKU que no cumplen el patron del validador del modulo 8
      (`^SKU_[A-Za-z0-9_]+$`) se avisan por consola en vez de colarse en
      silencio hasta la validacion final. `SKU-001`, con guion normal, es el
      caso que se dio.
    """
    if ruta is None:
        return {}
    ruta = Path(ruta)
    if not ruta.exists():
        raise FileNotFoundError(f"No existe el mapa de productos: {ruta}")
    with ruta.open("r", encoding="utf-8") as fh:
        data = json.load(fh)

    crudos = data.get("productos", data)
    productos: dict[str, str] = {}
    invalidos: list[str] = []

    for zone_id, sku in crudos.items():
        if zone_id.startswith("_"):  # claves de comentario en el JSON
            continue
        if sku is None or str(sku).strip() == "":
            continue  # zona de transito: no lleva producto
        sku = str(sku).strip()
        if not PATRON_SKU.match(sku):
            invalidos.append(f"{zone_id}: {sku}")
        productos[str(zone_id)] = sku

    if invalidos:
        print(
            "[aviso] SKU que no cumplen el patron ^SKU_[A-Za-z0-9_]+$ del "
            "validador del modulo 8 y haran fallar la validacion: "
            + ", ".join(invalidos)
        )

    return productos


def a_iso(t0: datetime, timestamp_ms: float) -> str:
    """
    Convierte el tiempo relativo del video (ms desde el inicio) a un timestamp
    ISO 8601 absoluto.

    El validador del modulo 8 exige `timestamp` en formato ISO, mientras que
    todo el pipeline interno trabaja con `timestamp_ms` relativo. `--t0` es la
    hora real de inicio de la grabacion; sin ella el dato seria irreproducible.
    """
    return (t0 + timedelta(milliseconds=timestamp_ms)).isoformat(timespec="seconds")


def proyectar_compliance(
    evento: Evento, t0: datetime, productos: dict[str, str]
) -> dict[str, Any] | None:
    """
    Proyecta un evento canonico al esquema minimo del validador del modulo 8.

    Campos permitidos por Paula: track_id, zone_id, product_id, event_type,
    dwell_time_s, timestamp, bbox. Cualquier otro campo marca el registro como
    no conforme, asi que aqui se recorta todo lo demas (confianza, detalle,
    episodio_id) y se traduce timestamp_ms -> timestamp ISO.

    `bbox` esta permitido pero no se incluye: no aporta a las metricas y es el
    unico campo del esquema que aproxima la posicion corporal. Minimizacion de
    datos, articulo 4 literal (c) de la Ley 1581 de 2012.

    Devuelve None para los eventos internos (takeaway), que no pertenecen al
    catalogo acordado.
    """
    if evento.event_type not in EVENTOS_COMPLIANCE:
        return None

    registro = {
        "track_id": evento.track_id,
        "zone_id": evento.zone_id,
        "event_type": evento.event_type,
        "dwell_time_s": round(max(0.0, evento.dwell_time_s), 2),
        "timestamp": a_iso(t0, evento.timestamp_ms),
    }
    sku = productos.get(evento.zone_id)
    if sku:
        registro["product_id"] = sku
    return registro


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Deteccion de eventos de interaccion en gondola — GondHawk modulo 1"
    )
    parser.add_argument("--tracking", required=True, help="tracking.jsonl (modulo 3)")
    parser.add_argument("--zonas", required=True, help="zonas.json (modulo 4)")
    parser.add_argument("--dwell", default=None, help="dwell_time.jsonl (modulo 5, opcional)")
    parser.add_argument("--productos", default=None, help="mapa zone_id -> SKU (opcional)")
    parser.add_argument("--outdir", default="deteccion_eventos/output", help="carpeta de salida")

    parser.add_argument(
        "--min-dwell",
        type=float,
        default=2.0,
        help="segundos para considerar que la persona se detuvo (default: 2.0, igual al modulo 5)",
    )
    parser.add_argument(
        "--gracia-frames",
        type=int,
        default=5,
        help="frames que puede desaparecer un track sin cerrar su episodio (default: 5)",
    )
    parser.add_argument(
        "--modo-alcance",
        choices=["geometrico", "pose"],
        default="geometrico",
        help="senal usada para detectar el alcance (default: geometrico)",
    )
    parser.add_argument(
        "--umbral-entrada",
        type=float,
        default=ReachConfig.umbral_entrada,
        help="expansion relativa del aspecto del bbox que inicia un alcance",
    )
    parser.add_argument(
        "--umbral-salida",
        type=float,
        default=ReachConfig.umbral_salida,
        help="expansion por debajo de la cual termina el alcance (histeresis)",
    )
    parser.add_argument(
        "--min-confianza",
        type=float,
        default=0.0,
        help="descarta alcances con confianza inferior (0-1)",
    )
    parser.add_argument(
        "--t0",
        default="2026-08-20T09:00:00",
        help="hora real de inicio del video, ISO 8601 (para el campo timestamp)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    try:
        t0 = datetime.fromisoformat(args.t0)
    except ValueError:
        raise SystemExit(f"--t0 no es una fecha ISO valida: {args.t0}")

    layout = cargar_layout(args.zonas)
    productos = cargar_productos(args.productos)
    dwell_index = DwellIndex.desde_archivo(args.dwell)

    maquina = InteractionStateMachine(
        layout=layout,
        config=InteractionConfig(
            min_dwell_s=args.min_dwell,
            gracia_frames=args.gracia_frames,
            min_confianza=args.min_confianza,
        ),
        reach_config=ReachConfig(
            umbral_entrada=args.umbral_entrada,
            umbral_salida=args.umbral_salida,
        ),
        modo_alcance=args.modo_alcance,
    )

    ultimo_ts = 0.0
    frames = 0
    for frame in leer_tracking(Path(args.tracking)):
        ultimo_ts = float(frame.get("timestamp_ms", ultimo_ts))
        maquina.process_frame(ultimo_ts, frame.get("tracks", []))
        frames += 1
    maquina.finalize(ultimo_ts)

    eventos = maquina.eventos

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    # 1. Formato canonico (interno del proyecto)
    ruta_canonica = outdir / "eventos_interaccion.jsonl"
    with ruta_canonica.open("w", encoding="utf-8") as fh:
        for evento in eventos:
            registro = evento.to_dict()
            cruce = dwell_index.buscar(
                evento.track_id, evento.zone_id, evento.timestamp_ms
            )
            if cruce is not None:
                registro["dwell_modulo5_s"] = cruce.get("dwell_time_s")
                registro["detuvo_modulo5"] = cruce.get("detuvo")
            fh.write(json.dumps(registro, ensure_ascii=False) + "\n")

    # 2. Proyeccion que pasa el validador del modulo 8
    ruta_compliance = outdir / "eventos_compliance.jsonl"
    n_compliance = 0
    with ruta_compliance.open("w", encoding="utf-8") as fh:
        for evento in eventos:
            registro = proyectar_compliance(evento, t0, productos)
            if registro is not None:
                fh.write(json.dumps(registro, ensure_ascii=False) + "\n")
                n_compliance += 1

    # 3. Metricas del embudo
    metricas = calcular_metricas(eventos, [z.zone_id for z in layout.gondolas])
    metricas["meta"] = {
        "video_ref": layout.metadata.get("video_ref"),
        "frames_procesados": frames,
        "t0": t0.isoformat(),
        "min_dwell_s": args.min_dwell,
        "modo_alcance": args.modo_alcance,
    }
    ruta_metricas = outdir / "metricas_interaccion.json"
    ruta_metricas.write_text(
        json.dumps(metricas, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 4. Diagnostico de integracion (para las reuniones de equipo)
    cruzados = sum(
        1
        for e in eventos
        if dwell_index.buscar(e.track_id, e.zone_id, e.timestamp_ms) is not None
    )
    reporte = {
        "resumen_maquina": maquina.resumen,
        "eventos_canonicos": len(eventos),
        "eventos_compliance": n_compliance,
        "eventos_internos_no_exportados": len(eventos) - n_compliance,
        "zonas_cargadas": [z.zone_id for z in layout],
        "gondolas": [z.zone_id for z in layout.gondolas],
        "dwell_modulo5": {
            "registros": len(dwell_index),
            "eventos_cruzados": cruzados,
            "sin_cruce": len(eventos) - cruzados,
        },
        "alcances_descartados": maquina.alcances_descartados[:50],
    }
    (outdir / "reporte_integracion.json").write_text(
        json.dumps(reporte, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # -- Consola -----------------------------------------------------------
    print(f"[ok] Frames procesados: {frames}")
    print(f"[ok] Zonas de gondola: {len(layout.gondolas)}")
    print(f"[ok] Detector de alcance: {maquina.detector.nombre}")
    print(f"[ok] Episodios (visitas a gondola): {maquina.resumen['episodios']}")
    print(f"[ok] Eventos generados: {len(eventos)}")
    for tipo, n in sorted(maquina.resumen["eventos_por_tipo"].items()):
        print(f"[ok]   {tipo}: {n}")
    print(f"[ok] Alcances descartados por filtros: {len(maquina.alcances_descartados)}")

    total = metricas["total"]
    print(
        f"[ok] Embudo global: {total['visitas']} visitas -> "
        f"{total['se_detiene']} paradas -> {total['toma_producto']} tomas -> "
        f"{total['devuelve']} devoluciones"
    )
    print(f"[ok] Tasa de interaccion: {total['tasa_interaccion']:.1%}")
    print(f"[ok] Tasa de rechazo: {total['tasa_rechazo']:.1%}")

    if dwell_index:
        print(
            f"[ok] Cruce con modulo 5: {cruzados}/{len(eventos)} eventos con dwell asociado"
        )

    for alerta in metricas["alertas"]:
        print(f"[!] {alerta['zone_id']} — {alerta['tipo']}: {alerta['mensaje']}")

    print(f"\n[ok] Salidas en: {outdir}")


if __name__ == "__main__":
    main()
