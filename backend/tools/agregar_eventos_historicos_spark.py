"""Agrega eventos archivados con PySpark, fuera del flujo principal.

Instalacion opcional: pip install pyspark
Uso desde la raiz: python backend/tools/agregar_eventos_historicos_spark.py
"""

from __future__ import annotations

import argparse
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Agrega eventos historicos por zona y tipo usando PySpark."
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "pipeline" / "output" / "analisis",
        help="Carpeta de analisis archivados.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[1]
        / "pipeline"
        / "output"
        / "agregados_eventos_spark",
        help="Carpeta de salida Parquet.",
    )
    args = parser.parse_args()

    archivos = sorted(args.input_dir.glob("*/eventos_interaccion.jsonl"))
    if not archivos:
        parser.error(f"No hay eventos historicos en {args.input_dir}")

    try:
        from pyspark.sql import SparkSession
        from pyspark.sql.functions import count, countDistinct, input_file_name, regexp_extract
    except ImportError as exc:
        raise SystemExit(
            "PySpark no esta instalado. Instala la dependencia opcional con: pip install pyspark"
        ) from exc

    spark = SparkSession.builder.appName("GondHawkEventosHistoricos").getOrCreate()
    try:
        eventos = spark.read.json([str(path) for path in archivos]).withColumn(
            "analisis_id",
            regexp_extract(input_file_name(), r"analisis/([^/]+)/", 1),
        )
        agregados = eventos.groupBy("zone_id", "event_type").agg(
            count("*").alias("total_eventos"),
            countDistinct("analisis_id").alias("analisis_con_eventos"),
        )
        agregados.write.mode("overwrite").parquet(str(args.output))
        print(f"Agregados guardados en {args.output}")
    finally:
        spark.stop()


if __name__ == "__main__":
    main()