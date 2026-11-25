"""
paralelo.py
Procesamiento paralelo por lotes — GondHawk (Computación Paralela y Distribuida)

Problema que resuelve
---------------------
El lote original repartía UN VIDEO POR PROCESO. Medido sobre dos videos
(859 y 379 frames) dio S(2) = 0,98: no aceleró, por tres causas:

  1. Sobresuscripción: cada proceso arrancaba PyTorch con todos los núcleos,
     así que dos procesos se disputaban el CPU.
  2. Desbalance: el lote esperaba al video más largo (techo teórico ≈ 1,36).
  3. Recarga del modelo YOLO en cada proceso y en cada video.

Estrategia (paralelismo de datos por rangos de frames)
------------------------------------------------------
  Fase 0 — escena : se verifica en paralelo que cada video sea retail, antes
                    de gastar inferencia (igual que hacía el pipeline).
  Fase 1 — detección : lo caro (YOLO) NO tiene estado entre frames, así que
                    cada video se parte en rangos de frames y todos los
                    rangos de todos los videos se reparten entre los procesos.
                    El trabajo queda balanceado aunque los videos midan
                    distinto, y un solo video también se acelera.
  Fase 2 — pipeline : seguimiento, eventos, heatmap y video anotado SÍ tienen
                    estado, así que corren completos por video (un video por
                    proceso), pero consumen las detecciones ya calculadas.

Además:
  * Cada worker limita sus hilos (núcleos // workers) → sin sobresuscripción.
  * El modelo se carga y se calienta UNA vez por worker (initializer).
  * El pool se conserva entre peticiones: el segundo lote ya no paga el arranque.

Los resultados son idénticos al modo secuencial: las detecciones de un frame no
dependen de qué proceso las calculó, y el seguimiento sigue siendo secuencial.
"""

from __future__ import annotations

import atexit
import math
import os
import sys
import threading
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]  # .../backend

_DETECTOR = None  # un detector YOLO por proceso worker
_POOL: ProcessPoolExecutor | None = None
_POOL_CFG: tuple[int, int] | None = None
_LOCK = threading.Lock()


# ── Configuración ───────────────────────────────────────────────────────────

def hilos_por_worker(workers: int, cpus: int | None = None) -> int:
    """Hilos de cómputo que le tocan a cada worker para no sobresuscribir."""
    cpus = cpus or os.cpu_count() or 1
    return max(1, cpus // max(1, workers))


def workers_por_defecto(cpus: int | None = None, tope: int = 4) -> int:
    """Workers sugeridos: ~núcleos físicos (lógicos // 2), con tope por memoria.

    Cada worker carga su propio YOLO + PyTorch (cientos de MB). Más procesos que
    núcleos físicos rara vez ayuda en inferencia de CPU y sí gasta RAM.
    """
    cpus = cpus or os.cpu_count() or 1
    return max(1, min(tope, cpus // 2 if cpus >= 4 else cpus))


def _asegurar_rutas() -> None:
    for sub in ("pipeline/src", "deteccion_personas/src"):
        ruta = str(ROOT / sub)
        if ruta not in sys.path:
            sys.path.insert(0, ruta)


def _obtener_detector():
    """Detector YOLO del proceso: se carga una sola vez y se reutiliza."""
    global _DETECTOR
    if _DETECTOR is None:
        _asegurar_rutas()
        from person_detector import PersonDetector

        _DETECTOR = PersonDetector(perfil="sintetico")  # mismo perfil que pipeline.py
    return _DETECTOR


def _inicializar_worker(hilos: int) -> None:
    """Se ejecuta una vez al crear cada proceso del pool."""
    texto = str(max(1, hilos))
    for var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
                "NUMEXPR_NUM_THREADS"):
        os.environ[var] = texto
    _asegurar_rutas()
    import cv2
    import numpy as np
    import torch

    cv2.setNumThreads(max(1, hilos))
    torch.set_num_threads(max(1, hilos))
    try:
        torch.set_num_interop_threads(1)
    except RuntimeError:
        pass  # ya fijado; no es un error

    detector = _obtener_detector()
    # Calentamiento: la primera inferencia inicializa buffers y es más lenta.
    detector.detect_frame(np.zeros((540, 960, 3), dtype=np.uint8))


# ── Tareas (funciones de módulo: deben poder importarse en Windows/spawn) ───

def _tarea_escena(job: dict[str, Any]) -> dict[str, Any]:
    _asegurar_rutas()
    from preproceso import evaluar_escena_retail, muestrear_frames

    resultado = evaluar_escena_retail(
        muestrear_frames(str(job["video_source"])),
        umbral=job.get("umbral_escena", 0.45),
    )
    return {
        "es_retail": resultado.es_retail,
        "motivo": resultado.motivo,
        "escena": resultado.to_dict(),
    }


def _tarea_detectar(
    idx: int, video: str, inicio: int, fin: int | None, salto: int
) -> tuple[int, dict[int, list[dict[str, Any]]]]:
    """Detecta personas en los frames [inicio, fin) con id % salto == 0.

    Lee el video en secuencia (grab() descarta sin convertir los frames que no
    se procesan), así que el resultado es exactamente el del bucle original;
    saltar con CAP_PROP_POS_FRAMES no es fiable en todos los códecs.
    """
    import cv2

    cap = cv2.VideoCapture(video)
    if not cap.isOpened():
        raise RuntimeError(f"OpenCV no pudo abrir {video}")
    detector = _obtener_detector()
    salida: dict[int, list[dict[str, Any]]] = {}
    try:
        fid = 0
        while fid < inicio:
            if not cap.grab():
                return idx, salida
            fid += 1
        while fin is None or fid < fin:
            if fid % salto == 0:
                ok, frame = cap.read()
                if not ok:
                    break
                salida[fid] = [d.to_dict() for d in detector.detect_frame(frame)]
            elif not cap.grab():
                break
            fid += 1
    finally:
        cap.release()
    return idx, salida


def _tarea_pipeline(
    job: dict[str, Any],
    detecciones: dict[int, list[dict[str, Any]]] | None,
    escena: dict[str, Any] | None,
) -> dict[str, Any]:
    try:
        _asegurar_rutas()
        from pipeline import GondolaPipeline

        necesita_detector = detecciones is None or job["zonas_auto"]
        pipeline = GondolaPipeline(
            video_source=job["video_source"],
            zonas_path=Path(job["zonas_path"]),
            outdir=Path(job["outdir"]),
            frame_skip=job["frame_skip"],
            zonas_auto=job["zonas_auto"],
            max_frames=job.get("max_frames"),
            detector=_obtener_detector() if necesita_detector else None,
            detecciones_precalculadas=detecciones,
            escena_precalculada=escena,
        )
        return {"ok": True, "resumen": pipeline.run()}
    except Exception as exc:  # noqa: BLE001 — el error queda aislado a este video
        return {"ok": False, "error": str(exc)}


# ── Planificación ───────────────────────────────────────────────────────────

def contar_frames(video: str) -> int:
    import cv2

    cap = cv2.VideoCapture(video)
    try:
        return int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) if cap.isOpened() else 0
    finally:
        cap.release()


def planificar_rangos(
    total_frames: int, salto: int, frames_por_rango: int, max_frames: int | None = None
) -> list[tuple[int, int | None]]:
    """Parte un video en rangos [inicio, fin) alineados a múltiplos de `salto`.

    El último rango queda abierto (fin=None) para cubrir hasta el final real
    aunque CAP_PROP_FRAME_COUNT sea inexacto. Con total_frames <= 0 (conteo
    desconocido) se devuelve un único rango.
    """
    limite = max_frames if max_frames is not None else None
    if total_frames <= 0:
        return [(0, limite)]
    if limite is not None:
        total_frames = min(total_frames, limite)
    paso = max(1, frames_por_rango) * salto
    inicios = list(range(0, total_frames, paso))
    rangos = [(i, i + paso) for i in inicios]
    ultimo_inicio = rangos[-1][0]
    rangos[-1] = (ultimo_inicio, limite)
    return rangos


# ── Pool persistente ────────────────────────────────────────────────────────

def _obtener_pool(workers: int, hilos: int) -> ProcessPoolExecutor:
    global _POOL, _POOL_CFG
    if _POOL is not None and _POOL_CFG != (workers, hilos):
        cerrar_pool()
    if _POOL is None:
        _POOL = ProcessPoolExecutor(
            max_workers=workers,
            initializer=_inicializar_worker,
            initargs=(hilos,),
        )
        _POOL_CFG = (workers, hilos)
    return _POOL


def cerrar_pool() -> None:
    global _POOL, _POOL_CFG
    if _POOL is not None:
        _POOL.shutdown(wait=True, cancel_futures=True)
    _POOL, _POOL_CFG = None, None


atexit.register(cerrar_pool)


# ── Orquestador ─────────────────────────────────────────────────────────────

def ejecutar_lote_por_chunks(
    jobs: list[dict[str, Any]],
    workers: int,
    hilos: int | None = None,
    rangos_por_worker: int = 4,
    min_frames_por_rango: int = 16,
    reutilizar_pool: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Procesa un lote de videos con paralelismo por rangos de frames.

    Cada job usa las mismas claves que el lote original (video_source,
    zonas_path, outdir, frame_skip, zonas_auto) y opcionalmente max_frames.
    Devuelve (resultados en el orden de `jobs`, detalle de tiempos).
    """
    workers = max(1, int(workers))
    hilos = hilos or hilos_por_worker(workers)
    with _LOCK:  # un lote a la vez: cada uno ya satura el CPU
        t_ini = time.perf_counter()
        pool = _obtener_pool(workers, hilos)
        resultados: list[dict[str, Any] | None] = [None] * len(jobs)

        # Fase 0 — verificación de escena
        t0 = time.perf_counter()
        escenas: dict[int, dict[str, Any] | None] = {}
        futuros = {
            pool.submit(_tarea_escena, j): i
            for i, j in enumerate(jobs)
            if j.get("verificar_escena", True)
        }
        for fut in as_completed(futuros):
            i = futuros[fut]
            try:
                r = fut.result()
            except Exception:  # noqa: BLE001 — pipeline.py volverá a verificar
                escenas[i] = None
                continue
            if r["es_retail"]:
                escenas[i] = r["escena"]
            else:
                resultados[i] = {"ok": False, "error": r["motivo"]}
        t_escena = time.perf_counter() - t0

        activos = [i for i in range(len(jobs)) if resultados[i] is None]

        # Fase 1 — detección por rangos de frames
        t0 = time.perf_counter()
        totales = {i: contar_frames(str(jobs[i]["video_source"])) for i in activos}
        procesados = {
            i: math.ceil(
                min(totales[i], jobs[i].get("max_frames") or totales[i])
                / jobs[i]["frame_skip"]
            )
            for i in activos
            if totales[i] > 0
        }
        objetivo = workers * rangos_por_worker
        por_rango = max(min_frames_por_rango, math.ceil(sum(procesados.values()) / objetivo)) \
            if procesados else min_frames_por_rango

        detecciones: dict[int, dict[int, list[dict[str, Any]]] | None] = {
            i: {} for i in activos
        }
        futuros = {}
        n_rangos = 0
        for i in activos:
            for inicio, fin in planificar_rangos(
                totales[i], jobs[i]["frame_skip"], por_rango, jobs[i].get("max_frames")
            ):
                fut = pool.submit(
                    _tarea_detectar, i, str(jobs[i]["video_source"]),
                    inicio, fin, jobs[i]["frame_skip"],
                )
                futuros[fut] = i
                n_rangos += 1
        for fut in as_completed(futuros):
            i = futuros[fut]
            try:
                _, parcial = fut.result()
                if detecciones[i] is not None:
                    detecciones[i].update(parcial)
            except Exception:  # noqa: BLE001
                # Ese video se detectará por su cuenta en la fase 2.
                detecciones[i] = None
        t_deteccion = time.perf_counter() - t0

        # Fase 2 — seguimiento, eventos, heatmap y video anotado, por video
        t0 = time.perf_counter()
        orden = sorted(activos, key=lambda i: procesados.get(i, 0), reverse=True)
        futuros = {
            pool.submit(_tarea_pipeline, jobs[i], detecciones[i], escenas.get(i)): i
            for i in orden
        }
        for fut in as_completed(futuros):
            i = futuros[fut]
            try:
                resultados[i] = fut.result()
            except Exception as exc:  # noqa: BLE001
                resultados[i] = {"ok": False, "error": f"Falló el worker: {exc}"}
        t_pipeline = time.perf_counter() - t0

        total = time.perf_counter() - t_ini
        if not reutilizar_pool:
            cerrar_pool()

    detalle = {
        "estrategia": "chunks",
        "workers": workers,
        "hilos_por_worker": hilos,
        "rangos_de_frames": n_rangos,
        "frames_por_rango": por_rango,
        "fase_escena_s": round(t_escena, 3),
        "fase_deteccion_s": round(t_deteccion, 3),
        "fase_pipeline_s": round(t_pipeline, 3),
        "total_s": round(total, 3),
    }
    return [r for r in resultados], detalle  # type: ignore[misc]
