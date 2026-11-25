from __future__ import annotations

import atexit
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Una sola sesión de Spark para todo el proceso, usada por una petición a la vez.
# Antes cada petición abría la sesión con getOrCreate() y la cerraba al terminar;
# si llegaban dos peticiones juntas (React StrictMode dispara el efecto dos veces
# en desarrollo) compartían la misma sesión y la primera se la cerraba a la
# segunda, que fallaba con "'NoneType' object has no attribute 'setCallSite'" y
# caía al fallback Python. Ahora la sesión se reutiliza y el candado serializa.
_spark_lock = threading.Lock()
_spark_session = None


def _obtener_spark():
    """Devuelve la sesión de Spark compartida, creándola la primera vez."""
    global _spark_session
    if _spark_session is not None:
        return _spark_session

    from pyspark.sql import SparkSession

    _spark_session = (
        SparkSession.builder.master("local[*]")
        .appName("GondHawkMetricasHistoricas")
        .config("spark.ui.enabled", "false")
        .getOrCreate()
    )
    _spark_session.sparkContext.setLogLevel("ERROR")
    return _spark_session


def _descartar_spark() -> None:
    """Cierra la sesión compartida para que la próxima petición cree una nueva."""
    global _spark_session
    if _spark_session is None:
        return
    try:
        _spark_session.stop()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[spark] No se pudo cerrar la sesión: %s", exc)
    finally:
        _spark_session = None


def _cerrar_spark_al_salir() -> None:
    with _spark_lock:
        _descartar_spark()


atexit.register(_cerrar_spark_al_salir)


def _metricas_python(archivos: list[Path]) -> list[dict[str, Any]]:
    acumulados: dict[str, dict[str, float]] = {}
    for archivo in archivos:
        try:
            contenido = json.loads(archivo.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("[spark] Se omite %s: %s", archivo, exc)
            continue

        for zona in contenido.get("zonas", []):
            zone_id = zona.get("zone_id")
            if not zone_id:
                continue
            flujo = int((zona.get("embudo") or {}).get("visitas") or 0)
            dwell = float(zona.get("dwell_promedio_s") or 0.0)
            interaccion = float(zona.get("tasa_interaccion") or 0.0)
            rechazo = float(zona.get("tasa_rechazo") or 0.0)
            fila = acumulados.setdefault(
                zone_id,
                {
                    "flujo_total": 0,
                    "dwell_ponderado": 0.0,
                    "interaccion_ponderada": 0.0,
                    "rechazo_ponderado": 0.0,
                    "rendimiento_ponderado": 0.0,
                    "analisis_count": 0,
                },
            )
            fila["flujo_total"] += flujo
            fila["dwell_ponderado"] += dwell * flujo
            fila["interaccion_ponderada"] += interaccion * flujo
            fila["rechazo_ponderado"] += rechazo * flujo
            fila["rendimiento_ponderado"] += interaccion * (1.0 - rechazo) * flujo
            fila["analisis_count"] += 1

    resultado = []
    for zone_id, fila in sorted(acumulados.items()):
        flujo_total = fila["flujo_total"]
        divisor = flujo_total or 1
        resultado.append(
            {
                "zone_id": zone_id,
                "flujo_total": flujo_total,
                "dwell_promedio_s": round(fila["dwell_ponderado"] / divisor, 2),
                "interaccion_media_pct": round(fila["interaccion_ponderada"] / divisor * 100, 2),
                "rechazo_medio_pct": round(fila["rechazo_ponderado"] / divisor * 100, 2),
                "rendimiento_pct": round(fila["rendimiento_ponderado"] / divisor * 100, 2),
                "analisis_count": int(fila["analisis_count"]),
            }
        )
    return resultado


def calcular_metricas_historial(directorio_analisis: Path) -> dict[str, Any]:
    archivos = sorted(directorio_analisis.glob("*/metricas_interaccion.json"))
    inicio = time.perf_counter()
    print(f"[spark] Calculando métricas históricas desde {len(archivos)} análisis", flush=True)
    logger.info("[spark] Calculando métricas históricas desde %d análisis", len(archivos))

    if not archivos:
        duracion = round(time.perf_counter() - inicio, 3)
        print(f"[spark] Sin análisis históricos; fallback vacío en {duracion:.3f} s", flush=True)
        return {
            "engine": "python_fallback",
            "mensaje": "No hay análisis históricos archivados para agregar.",
            "duracion_s": duracion,
            "metricas": [],
        }

    with _spark_lock:
        return _calcular_con_spark(archivos, inicio)


def _calcular_con_spark(archivos: list[Path], inicio: float) -> dict[str, Any]:
    try:
        from pyspark.sql import functions as F

        spark = _obtener_spark()

        zonas = (
            spark.read.option("multiLine", "true")
            .json([str(archivo) for archivo in archivos])
            .select(F.explode_outer("zonas").alias("zona"))
            .select(
                F.col("zona.zone_id").alias("zone_id"),
                F.coalesce(F.col("zona.embudo.visitas").cast("double"), F.lit(0.0)).alias("flujo"),
                F.coalesce(F.col("zona.dwell_promedio_s").cast("double"), F.lit(0.0)).alias("dwell"),
                F.coalesce(F.col("zona.tasa_interaccion").cast("double"), F.lit(0.0)).alias("interaccion"),
                F.coalesce(F.col("zona.tasa_rechazo").cast("double"), F.lit(0.0)).alias("rechazo"),
            )
            .where(F.col("zone_id").isNotNull())
        )
        flujo_total = F.sum("flujo")
        metricas = (
            zonas.groupBy("zone_id")
            .agg(
                flujo_total.alias("flujo_total"),
                F.when(flujo_total > 0, F.sum(F.col("dwell") * F.col("flujo")) / flujo_total)
                .otherwise(F.lit(0.0)).alias("dwell_promedio_s"),
                F.when(flujo_total > 0, F.sum(F.col("interaccion") * F.col("flujo")) / flujo_total * 100)
                .otherwise(F.lit(0.0)).alias("interaccion_media_pct"),
                F.when(flujo_total > 0, F.sum(F.col("rechazo") * F.col("flujo")) / flujo_total * 100)
                .otherwise(F.lit(0.0)).alias("rechazo_medio_pct"),
                F.when(
                    flujo_total > 0,
                    F.sum(F.col("interaccion") * (1 - F.col("rechazo")) * F.col("flujo")) / flujo_total * 100,
                ).otherwise(F.lit(0.0)).alias("rendimiento_pct"),
                F.count(F.lit(1)).alias("analisis_count"),
            )
            .orderBy("zone_id")
        )
        filas = [
            {
                **fila.asDict(),
                "flujo_total": int(fila["flujo_total"] or 0),
                "dwell_promedio_s": round(float(fila["dwell_promedio_s"] or 0.0), 2),
                "interaccion_media_pct": round(float(fila["interaccion_media_pct"] or 0.0), 2),
                "rechazo_medio_pct": round(float(fila["rechazo_medio_pct"] or 0.0), 2),
                "rendimiento_pct": round(float(fila["rendimiento_pct"] or 0.0), 2),
                "analisis_count": int(fila["analisis_count"] or 0),
            }
            for fila in metricas.collect()
        ]
        duracion = round(time.perf_counter() - inicio, 3)
        print(f"[spark] Métricas calculadas con Apache Spark en {duracion:.3f} s", flush=True)
        logger.info("[spark] Métricas calculadas con Apache Spark en %.3f s", duracion)
        return {
            "engine": "apache_spark",
            "mensaje": "Métricas históricas calculadas con Apache Spark.",
            "duracion_s": duracion,
            "metricas": filas,
        }
    except Exception as exc:  # noqa: BLE001 — Spark y Java son opcionales al ejecutar
        logger.warning("[spark] Spark no disponible (%s); se usa fallback Python.", exc)
        # Si la sesión quedó en mal estado, se descarta para que la próxima
        # petición intente con una sesión nueva en vez de repetir el error.
        _descartar_spark()
        filas = _metricas_python(archivos)
        duracion = round(time.perf_counter() - inicio, 3)
        print(f"[spark] Fallback Python completado en {duracion:.3f} s", flush=True)
        logger.info("[spark] Fallback histórico completado en %.3f s", duracion)
        return {
            "engine": "python_fallback",
            "mensaje": f"Apache Spark no pudo ejecutarse ({exc}); se usó el agregado local.",
            "duracion_s": duracion,
            "metricas": filas,
        }
