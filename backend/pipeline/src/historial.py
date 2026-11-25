"""
historial.py
Historial de análisis — GondHawk.

Hoy el pipeline escribe siempre en la misma carpeta `output/`, así que cada
video nuevo pisa al anterior: no hay forma de volver a ver un análisis pasado
ni de comparar dos videos. Este módulo le da a cada corrida su propia carpeta y
mantiene un índice consultable.

Estructura que produce:

    output/
      indice.json                   ← lista de todas las corridas, más reciente primero
      analisis/
        2026-09-04T101423_tienda1/
          metricas_interaccion.json
          metricas_pipeline.json
          heatmap.png
          video_anotado.mp4
          eventos_interaccion.jsonl
          ...
        2026-09-04T094512_tienda2/
          ...

El índice guarda solo el resumen que necesita el frontend para pintar la lista
(fecha, nombre del video, KPIs principales); el detalle completo se lee de la
carpeta cuando el usuario abre esa corrida. Así la lista carga rápido aunque
haya 200 análisis.

Se usa un ID derivado de la marca de tiempo porque es ordenable
alfabéticamente: listar la carpeta ya devuelve las corridas en orden
cronológico, sin tener que abrir ningún archivo.
"""

from __future__ import annotations

import json
import re
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

NOMBRE_INDICE = "indice.json"
SUBCARPETA = "analisis"

# Archivos que se conservan por corrida. Los .npy del heatmap y el
# detecciones.jsonl crudo se excluyen a propósito: pesan mucho y son
# regenerables, y con 50 análisis guardados llenarían el disco.
ARCHIVOS_A_CONSERVAR = [
    "metricas_interaccion.json",
    "metricas_pipeline.json",
    "conteo_zonas.json",
    "reporte_integracion.json",
    "heatmap.png",
    "video_anotado.mp4",
    "zonas_propuestas.png",
    "zonas_propuestas.json",
    "zonas_usadas.json",
    "eventos_interaccion.jsonl",
    "eventos_compliance.jsonl",
    "dwell_time.jsonl",
    "tracking.jsonl",
]


# Un identificador de análisis es siempre "AAAAMMDDTHHMMSS_slug": solo
# letras, dígitos, guion y guion bajo. Validarlo es lo que impide que un
# `analisis_id` como "../../.." saque las rutas de la carpeta de análisis y
# permita leer —o borrar— cualquier carpeta del servidor a través de la API.
_ID_VALIDO = re.compile(r"^[A-Za-z0-9_.-]{1,120}$")


def id_valido(analisis_id: str) -> bool:
    return bool(analisis_id) and ".." not in analisis_id and bool(_ID_VALIDO.match(analisis_id))


def _slug(texto: str, largo: int = 40) -> str:
    limpio = re.sub(r"[^\w\-]+", "_", Path(texto).stem, flags=re.UNICODE)
    return limpio.strip("_")[:largo] or "video"


class HistorialAnalisis:
    """Gestiona las corridas guardadas bajo una carpeta de salida."""

    def __init__(self, output_dir: Path | str):
        self.output_dir = Path(output_dir)
        self.dir_analisis = self.output_dir / SUBCARPETA
        self.dir_analisis.mkdir(parents=True, exist_ok=True)
        self.ruta_indice = self.output_dir / NOMBRE_INDICE

    # ── Índice ────────────────────────────────────────────────────────────

    def _leer_indice(self) -> list[dict[str, Any]]:
        if not self.ruta_indice.exists():
            return []
        try:
            with self.ruta_indice.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data.get("analisis", []) if isinstance(data, dict) else []
        except (json.JSONDecodeError, OSError):
            # Un índice corrupto no debe tumbar el servidor: se reconstruye
            # desde las carpetas, que son la fuente de verdad real.
            return self.reconstruir_indice()

    def _escribir_indice(self, entradas: list[dict[str, Any]]) -> None:
        entradas.sort(key=lambda e: e.get("id", ""), reverse=True)
        payload = {
            "actualizado": datetime.now().isoformat(timespec="seconds"),
            "total": len(entradas),
            "analisis": entradas,
        }
        tmp = self.ruta_indice.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.ruta_indice)  # escritura atómica: nunca queda a medias

    # ── Registro de una corrida ───────────────────────────────────────────

    def registrar(
        self,
        nombre_video: str,
        resumen: dict[str, Any],
        origen: Path | str | None = None,
    ) -> dict[str, Any]:
        """
        Copia las salidas de una corrida a su propia carpeta y la indexa.

        `origen` es la carpeta donde el pipeline dejó los archivos (por defecto
        la propia output_dir). Devuelve la entrada del índice.
        """
        origen = Path(origen) if origen else self.output_dir
        ahora = datetime.now()
        prefijo_id = f"{ahora.strftime('%Y%m%dT%H%M%S')}_{_slug(nombre_video)}"
        while True:
            analisis_id = f"{prefijo_id}_{uuid.uuid4().hex[:8]}"
            destino = self.dir_analisis / analisis_id
            try:
                destino.mkdir(parents=True, exist_ok=False)
                break
            except FileExistsError:
                continue

        archivos: dict[str, str] = {}
        for nombre in ARCHIVOS_A_CONSERVAR:
            fuente = origen / nombre
            if fuente.exists() and fuente.is_file():
                shutil.copy2(fuente, destino / nombre)
                archivos[nombre] = f"{SUBCARPETA}/{analisis_id}/{nombre}"

        entrada = {
            "id": analisis_id,
            "fecha": ahora.isoformat(timespec="seconds"),
            "video": nombre_video,
            "archivos": archivos,
            "resumen": self._extraer_resumen(resumen),
        }

        with (destino / "resumen.json").open("w", encoding="utf-8") as fh:
            json.dump({**entrada, "detalle": resumen}, fh, ensure_ascii=False, indent=2)

        entradas = [e for e in self._leer_indice() if e.get("id") != analisis_id]
        entradas.append(entrada)
        self._escribir_indice(entradas)
        return entrada

    @staticmethod
    def _extraer_resumen(resumen: dict[str, Any]) -> dict[str, Any]:
        """
        Aplana los KPIs que el frontend muestra en la lista del historial.

        Se hace aquí y no en el frontend para que la lista no tenga que abrir
        el JSON completo de cada corrida.
        """
        interaccion = resumen.get("interaction") or resumen.get("metricas_interaccion") or {}
        total = interaccion.get("total", {}) if isinstance(interaccion, dict) else {}
        pipeline = resumen.get("pipeline", resumen) if isinstance(resumen, dict) else {}

        return {
            "personas": pipeline.get("personas_unicas") or pipeline.get("total_tracks"),
            "frames": pipeline.get("frames_procesados"),
            "duracion_analisis_s": pipeline.get("tiempo_procesamiento_seg"),
            "visitas": total.get("visitas"),
            "se_detiene": total.get("se_detiene"),
            "toma_producto": total.get("toma_producto"),
            "devuelve": total.get("devuelve"),
            "tasa_interaccion": total.get("tasa_interaccion"),
            "tasa_rechazo": total.get("tasa_rechazo"),
        }

    # ── Consulta ──────────────────────────────────────────────────────────

    def listar(self, limite: int | None = None) -> list[dict[str, Any]]:
        """Corridas de la más reciente a la más antigua."""
        entradas = self._leer_indice()
        return entradas[:limite] if limite else entradas

    def obtener(self, analisis_id: str) -> dict[str, Any] | None:
        """Detalle completo de una corrida, leído de su carpeta."""
        ruta = self.dir_analisis / analisis_id / "resumen.json"
        if not ruta.exists():
            return None
        with ruta.open("r", encoding="utf-8") as fh:
            return json.load(fh)

    def ruta_archivo(self, analisis_id: str, nombre: str) -> Path | None:
        """
        Ruta de un archivo de una corrida, validando que no se escape de la
        carpeta. Sin esta comprobación, un `nombre` como `../../etc/passwd`
        serviría para leer cualquier archivo del servidor a través de la API.
        """
        if not id_valido(analisis_id):
            return None
        base = (self.dir_analisis / analisis_id).resolve()
        candidato = (base / nombre).resolve()
        if base != candidato and base not in candidato.parents:
            return None
        return candidato if candidato.exists() and candidato.is_file() else None

    def eliminar(self, analisis_id: str) -> bool:
        if not id_valido(analisis_id):
            return False
        destino = self.dir_analisis / analisis_id
        if not destino.exists():
            return False
        shutil.rmtree(destino)
        self._escribir_indice([e for e in self._leer_indice() if e.get("id") != analisis_id])
        return True

    def reconstruir_indice(self) -> list[dict[str, Any]]:
        """Rearma el índice leyendo las carpetas. Útil si el JSON se corrompe."""
        entradas = []
        for carpeta in sorted(self.dir_analisis.iterdir(), reverse=True):
            resumen = carpeta / "resumen.json"
            if not (carpeta.is_dir() and resumen.exists()):
                continue
            try:
                with resumen.open("r", encoding="utf-8") as fh:
                    data = json.load(fh)
                data.pop("detalle", None)
                entradas.append(data)
            except (json.JSONDecodeError, OSError):
                continue
        self._escribir_indice(entradas)
        return entradas

    def estadisticas(self) -> dict[str, Any]:
        """Agregados sobre todo el historial, para la vista de reportes."""
        entradas = self._leer_indice()
        if not entradas:
            return {"total_analisis": 0}

        def promedio(campo: str) -> float | None:
            valores = [
                e["resumen"][campo]
                for e in entradas
                if isinstance(e.get("resumen", {}).get(campo), (int, float))
            ]
            return round(sum(valores) / len(valores), 4) if valores else None

        return {
            "total_analisis": len(entradas),
            "primer_analisis": entradas[-1]["fecha"],
            "ultimo_analisis": entradas[0]["fecha"],
            "promedio_tasa_interaccion": promedio("tasa_interaccion"),
            "promedio_tasa_rechazo": promedio("tasa_rechazo"),
            "total_visitas": sum(
                e["resumen"].get("visitas") or 0 for e in entradas
            ),
        }
