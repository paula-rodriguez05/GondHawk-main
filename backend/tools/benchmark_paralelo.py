"""
benchmark_paralelo.py — mide speedup y eficiencia del procesamiento paralelo.

Compara, sobre los MISMOS videos:
  base      : pipeline secuencial original (un video tras otro, sin paralelismo)
  videos    : modo anterior, un video por proceso (--legacy)
  chunks p  : modo nuevo, detección repartida por rangos de frames, p workers

  S(p) = T_base / T_p        E(p) = S(p) / p

Uso (desde backend/, con el .venv activo):
    python tools/benchmark_paralelo.py VIDEO1.mp4 VIDEO2.mp4 --frame-skip 3 \\
        --workers 1 2 4 --legacy

    # prueba rápida: solo los primeros 300 frames de cada video
    python tools/benchmark_paralelo.py VIDEO1.mp4 --max-frames 300 --workers 1 2

Escribe pipeline/output/benchmark/resultados_benchmark.{json,md}.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline" / "src"))

ZONAS = ROOT / "mapas_de_calor" / "config" / "zonas.json"
SALIDA = ROOT / "pipeline" / "output" / "benchmark"


def crear_jobs(videos, frame_skip, max_frames, etiqueta):
    base = SALIDA / etiqueta
    if base.exists():
        shutil.rmtree(base, ignore_errors=True)
    jobs = []
    for i, v in enumerate(videos):
        jobs.append({
            "video_source": str(Path(v).resolve()),
            "zonas_path": str(ZONAS),
            "outdir": str(base / str(i)),
            "frame_skip": frame_skip,
            "zonas_auto": False,
            "max_frames": max_frames,
            "nombre_video": Path(v).name,
        })
    return jobs


def firma(resultados):
    """Lo que debe ser idéntico entre modos: paralelizar no cambia las métricas."""
    out = []
    for r in resultados:
        if not r.get("ok"):
            out.append({"error": r.get("error")})
            continue
        res = r["resumen"]
        out.append({
            "frames": res["frames_procesados"],
            "detecciones": res["total_detecciones"],
            "eventos": res["eventos_generados"],
            "embudo": res["embudo_global"],
        })
    return out


def correr_base(videos, frame_skip, max_frames):
    """Pipeline original, secuencial, tal como corría antes de paralelizar."""
    from pipeline import GondolaPipeline

    jobs = crear_jobs(videos, frame_skip, max_frames, "base")
    t0 = time.perf_counter()
    res = []
    for j in jobs:
        try:
            pipe = GondolaPipeline(
                video_source=j["video_source"], zonas_path=Path(j["zonas_path"]),
                outdir=Path(j["outdir"]), frame_skip=frame_skip,
                max_frames=max_frames, zonas_auto=False,
            )
            res.append({"ok": True, "resumen": pipe.run()})
        except Exception as exc:  # noqa: BLE001
            res.append({"ok": False, "error": str(exc)})
    return time.perf_counter() - t0, res


def correr_legacy(videos, frame_skip, max_frames, p):
    import api_server  # reutiliza exactamente el código del endpoint anterior

    jobs = crear_jobs(videos, frame_skip, max_frames, f"videos_p{p}")
    t0 = time.perf_counter()
    res = api_server._ejecutar_lote_en_procesos(jobs, min(p, len(jobs)))
    return time.perf_counter() - t0, res


def correr_chunks(videos, frame_skip, max_frames, p, hilos):
    import paralelo

    jobs = crear_jobs(videos, frame_skip, max_frames, f"chunks_p{p}")
    t0 = time.perf_counter()
    res, detalle = paralelo.ejecutar_lote_por_chunks(jobs, p, hilos)
    return time.perf_counter() - t0, res, detalle


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("videos", nargs="+")
    ap.add_argument("--frame-skip", type=int, default=3)
    ap.add_argument("--max-frames", type=int, default=None)
    ap.add_argument("--workers", type=int, nargs="+", default=[1, 2, 4])
    ap.add_argument("--hilos", type=int, default=None, help="hilos por worker (default: núcleos // workers)")
    ap.add_argument("--legacy", action="store_true", help="incluir el modo anterior (un video por proceso)")
    ap.add_argument("--repeticiones", type=int, default=1,
                    help="2 = además mide con el pool ya caliente (segunda corrida)")
    ap.add_argument("--sin-base", action="store_true", help="omitir el secuencial (muy lento)")
    a = ap.parse_args()

    SALIDA.mkdir(parents=True, exist_ok=True)
    filas, firmas = [], {}
    print(f"[bench] {len(a.videos)} videos | núcleos lógicos: {os.cpu_count()} | skip={a.frame_skip} | max_frames={a.max_frames}")

    t_base = None
    if not a.sin_base:
        print("[bench] base secuencial ...", flush=True)
        t_base, res = correr_base(a.videos, a.frame_skip, a.max_frames)
        firmas["base"] = firma(res)
        filas.append({"modo": "base (secuencial)", "p": 1, "tiempo_s": t_base})
        print(f"[bench]   {t_base:.1f} s")

    if a.legacy:
        for p in a.workers:
            print(f"[bench] videos (modo anterior) p={p} ...", flush=True)
            t, res = correr_legacy(a.videos, a.frame_skip, a.max_frames, p)
            firmas[f"videos_p{p}"] = firma(res)
            filas.append({"modo": "un video por proceso", "p": p, "tiempo_s": t})
            print(f"[bench]   {t:.1f} s")

    for p in a.workers:
        for rep in range(a.repeticiones):
            etiqueta = "frío" if rep == 0 else "caliente"
            print(f"[bench] chunks p={p} ({etiqueta}) ...", flush=True)
            t, res, det = correr_chunks(a.videos, a.frame_skip, a.max_frames, p, a.hilos)
            firmas[f"chunks_p{p}_{etiqueta}"] = firma(res)
            filas.append({"modo": f"rangos de frames ({etiqueta})", "p": p, "tiempo_s": t, "detalle": det})
            print(f"[bench]   {t:.1f} s  {det}")
        import paralelo
        paralelo.cerrar_pool()

    ref = t_base if t_base else next((f["tiempo_s"] for f in filas if f["p"] == 1), None)
    for f in filas:
        if ref:
            f["speedup"] = ref / f["tiempo_s"]
            f["eficiencia"] = f["speedup"] / f["p"]

    base_firma = next(iter(firmas.values()), None)
    identicos = all(v == base_firma for v in firmas.values())

    md = ["| Modo | p | Tiempo (s) | S(p) | E(p) |", "|---|---|---|---|---|"]
    for f in filas:
        md.append(f"| {f['modo']} | {f['p']} | {f['tiempo_s']:.1f} | "
                  f"{f.get('speedup', float('nan')):.2f} | {f.get('eficiencia', float('nan')):.2f} |")
    tabla = "\n".join(md)
    print("\n" + tabla)
    print(f"\nResultados idénticos entre modos: {'SÍ' if identicos else 'NO (revisar)'}")
    if not identicos:
        for k, v in firmas.items():
            print(" ", k, v)

    (SALIDA / "resultados_benchmark.json").write_text(
        json.dumps({"nucleos": os.cpu_count(), "frame_skip": a.frame_skip, "max_frames": a.max_frames,
                    "videos": [Path(v).name for v in a.videos], "filas": filas,
                    "resultados_identicos": identicos, "firmas": firmas},
                   indent=2, ensure_ascii=False), encoding="utf-8")
    (SALIDA / "resultados_benchmark.md").write_text(tabla + "\n", encoding="utf-8")
    print(f"\nGuardado en {SALIDA}")


if __name__ == "__main__":
    main()
