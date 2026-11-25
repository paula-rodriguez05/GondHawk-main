"""
Persistencia de análisis en Supabase.

Extiende el historial en disco en vez de reemplazarlo. La razón es práctica:
el pipeline y la API ya leen archivos por ruta local (heatmap, video anotado,
tracking.jsonl), y reescribir todo eso para que hable con Storage sería una
cirugía innecesaria. El disco pasa a ser una caché; la fuente de verdad es
Supabase.

Esto es lo que hace escalable el sistema:

  - Varias instancias de la API comparten el mismo historial. Antes, cada
    servidor tenía su propio `indice.json` y no se veían entre sí.
  - Las métricas por zona y los eventos quedan consultables con SQL, así que
    "cómo se comportó la góndola 3 este mes" es una consulta y no abrir
    treinta archivos.
  - Si el contenedor se recicla, el historial sobrevive.

Si no hay credenciales configuradas, todo sigue funcionando exactamente como
antes contra el disco. Eso es deliberado: la demo no puede depender de tener
internet.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from historial import ARCHIVOS_A_CONSERVAR, HistorialAnalisis, id_valido

# Artefactos que se suben a Storage. Los .jsonl grandes también van, porque el
# frontend los descarga para dibujar el mapa de tienda.
ARCHIVOS_A_SUBIR = set(ARCHIVOS_A_CONSERVAR)

BUCKET = os.getenv("SUPABASE_BUCKET", "gondhawk")

# Los eventos se insertan por lotes. Un video largo genera miles de filas y
# mandarlas en una sola petición hace que Supabase corte por tamaño.
LOTE_EVENTOS = 500


def _cliente():
    """
    Cliente de Supabase, o None si el proyecto no está configurado.

    Se usa la SERVICE ROLE KEY, no la anon key: el backend necesita escribir
    en tablas con RLS activo. Esa clave NUNCA debe llegar al frontend.
    """
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_KEY")
    if not url or not key:
        return None
    try:
        from supabase import create_client
    except ImportError:
        print("[almacen] Falta el paquete `supabase`. Instala: pip install supabase")
        return None
    try:
        return create_client(url, key)
    except Exception as exc:  # noqa: BLE001
        print(f"[almacen] No se pudo conectar a Supabase: {exc}")
        return None


class HistorialSupabase(HistorialAnalisis):
    """Historial que escribe en Supabase y usa el disco como caché."""

    def __init__(self, output_dir: Path | str, cliente=None):
        super().__init__(output_dir)
        self.sb = cliente if cliente is not None else _cliente()
        self.tienda_id = os.getenv("GONDHAWK_TIENDA_ID") or None
        self.camara_id = os.getenv("GONDHAWK_CAMARA_ID") or None

    @property
    def activo(self) -> bool:
        return self.sb is not None

    # ── Escritura ─────────────────────────────────────────────────────────

    def registrar(
        self,
        nombre_video: str,
        resumen: dict[str, Any],
        origen: Path | str | None = None,
    ) -> dict[str, Any]:
        # Primero el disco: si Supabase falla, el análisis no se pierde y la
        # respuesta al usuario sale igual.
        entrada = super().registrar(nombre_video, resumen, origen)
        if not self.activo:
            return entrada

        try:
            self._subir_archivos(entrada["id"])
            self._insertar_analisis(entrada, resumen)
            self._insertar_zonas(entrada["id"], resumen)
            self._insertar_eventos(entrada["id"])
        except Exception as exc:  # noqa: BLE001
            # Un fallo de red no puede tumbar un análisis que ya terminó bien.
            print(f"[almacen] No se pudo sincronizar {entrada['id']}: {exc}")
        return entrada

    def _subir_archivos(self, analisis_id: str) -> None:
        carpeta = self.dir_analisis / analisis_id
        for nombre in sorted(ARCHIVOS_A_SUBIR):
            ruta = carpeta / nombre
            if not ruta.exists() or not ruta.is_file():
                continue
            destino = f"{analisis_id}/{nombre}"
            self.sb.storage.from_(BUCKET).upload(
                destino,
                ruta.read_bytes(),
                {"content-type": _tipo_mime(ruta), "upsert": "true"},
            )

    def _insertar_analisis(self, entrada: dict[str, Any], resumen: dict[str, Any]) -> None:
        r = entrada.get("resumen", {})
        fila = {
            "id": entrada["id"],
            "fecha": entrada["fecha"],
            "video": entrada["video"],
            "sintetico": bool(resumen.get("sintetico")),
            "tienda_id": self.tienda_id,
            "camara_id": self.camara_id,
            "personas": r.get("personas"),
            "frames": r.get("frames"),
            "duracion_analisis_s": r.get("duracion_analisis_s"),
            "visitas": r.get("visitas"),
            "se_detiene": r.get("se_detiene"),
            "toma_producto": r.get("toma_producto"),
            "devuelve": r.get("devuelve"),
            "tasa_interaccion": r.get("tasa_interaccion"),
            "tasa_rechazo": r.get("tasa_rechazo"),
            "detalle": resumen,
            "archivos": entrada.get("archivos", {}),
        }
        self.sb.table("analisis").upsert(fila).execute()

    def _insertar_zonas(self, analisis_id: str, resumen: dict[str, Any]) -> None:
        interaccion = resumen.get("interaction") or {}
        zonas = interaccion.get("zonas") or []
        if not zonas:
            return

        # El conteo de ocupación vive en otro archivo; se cruza por zone_id
        # para dejar una sola fila completa por zona.
        conteo = {}
        ruta_conteo = self.ruta_archivo(analisis_id, "conteo_zonas.json")
        if ruta_conteo:
            datos = json.loads(ruta_conteo.read_text(encoding="utf-8"))
            conteo = {z["zone_id"]: z for z in datos.get("zonas", [])}

        poligonos = {}
        for nombre in ("zonas_usadas.json", "zonas_propuestas.json"):
            ruta = self.ruta_archivo(analisis_id, nombre)
            if ruta:
                datos = json.loads(ruta.read_text(encoding="utf-8"))
                poligonos = {
                    z["zone_id"]: z.get("poligono") for z in datos.get("zonas", [])
                }
                break

        filas = []
        for zona in zonas:
            zid = zona.get("zone_id")
            extra = conteo.get(zid, {})
            filas.append(
                {
                    "analisis_id": analisis_id,
                    "zone_id": zid,
                    "es_gondola": zona.get("es_gondola"),
                    "visitas": zona.get("visitas"),
                    "se_detiene": zona.get("se_detiene"),
                    "toma_producto": zona.get("toma_producto"),
                    "devuelve": zona.get("devuelve"),
                    "tasa_interaccion": zona.get("tasa_interaccion"),
                    "tasa_rechazo": zona.get("tasa_rechazo"),
                    "visitas_unicas": extra.get("visitas_unicas"),
                    "pct_tiempo_ocupada": extra.get("pct_tiempo_ocupada"),
                    "poligono": poligonos.get(zid),
                }
            )
        self.sb.table("zonas_metricas").upsert(
            filas, on_conflict="analisis_id,zone_id"
        ).execute()

    def _insertar_eventos(self, analisis_id: str) -> None:
        ruta = self.ruta_archivo(analisis_id, "eventos_interaccion.jsonl")
        if ruta is None:
            return

        lote: list[dict[str, Any]] = []
        with ruta.open("r", encoding="utf-8") as fh:
            for linea in fh:
                linea = linea.strip()
                if not linea:
                    continue
                try:
                    ev = json.loads(linea)
                except json.JSONDecodeError:
                    continue
                lote.append(
                    {
                        "analisis_id": analisis_id,
                        "person_id": ev.get("person_id"),
                        "zone_id": ev.get("zone_id"),
                        "event_type": ev.get("event_type"),
                        "timestamp_ms": ev.get("timestamp_ms"),
                        "confianza": ev.get("confianza") or ev.get("confidence"),
                    }
                )
                if len(lote) >= LOTE_EVENTOS:
                    self.sb.table("eventos").insert(lote).execute()
                    lote = []
        if lote:
            self.sb.table("eventos").insert(lote).execute()

    # ── Lectura ───────────────────────────────────────────────────────────

    def listar(self, limite: int | None = None) -> list[dict[str, Any]]:
        if not self.activo:
            return super().listar(limite)
        try:
            consulta = (
                self.sb.table("analisis")
                .select(
                    "id,fecha,video,sintetico,archivos,personas,frames,"
                    "duracion_analisis_s,visitas,se_detiene,toma_producto,"
                    "devuelve,tasa_interaccion,tasa_rechazo"
                )
                .order("fecha", desc=True)
            )
            if limite:
                consulta = consulta.limit(limite)
            filas = consulta.execute().data or []
        except Exception as exc:  # noqa: BLE001
            print(f"[almacen] Fallo al listar, se usa el disco: {exc}")
            return super().listar(limite)

        # Se devuelve con la MISMA forma que el índice en disco para que el
        # frontend no note el cambio de origen.
        return [
            {
                "id": f["id"],
                "fecha": f["fecha"],
                "video": f["video"],
                "archivos": f.get("archivos") or {},
                "resumen": {
                    campo: f.get(campo)
                    for campo in (
                        "personas", "frames", "duracion_analisis_s", "visitas",
                        "se_detiene", "toma_producto", "devuelve",
                        "tasa_interaccion", "tasa_rechazo",
                    )
                },
            }
            for f in filas
        ]

    def obtener(self, analisis_id: str) -> dict[str, Any] | None:
        local = super().obtener(analisis_id)
        if local is not None or not self.activo or not id_valido(analisis_id):
            return local
        try:
            filas = (
                self.sb.table("analisis")
                .select("*")
                .eq("id", analisis_id)
                .limit(1)
                .execute()
                .data
            )
        except Exception:  # noqa: BLE001
            return None
        if not filas:
            return None
        fila = filas[0]
        return {
            "id": fila["id"],
            "fecha": fila["fecha"],
            "video": fila["video"],
            "archivos": fila.get("archivos") or {},
            "detalle": fila.get("detalle") or {},
        }

    def estadisticas(self) -> dict[str, Any]:
        if not self.activo:
            return super().estadisticas()
        try:
            filas = self.sb.table("v_estadisticas_globales").select("*").execute().data
            if filas and filas[0].get("total_analisis"):
                return filas[0]
        except Exception as exc:  # noqa: BLE001
            print(f"[almacen] Fallo en estadísticas, se usa el disco: {exc}")
        return super().estadisticas()

    def ruta_archivo(self, analisis_id: str, nombre: str) -> Path | None:
        """
        Ruta local del archivo, descargándolo de Storage si no está en caché.

        Esto es lo que permite que una instancia nueva de la API sirva el video
        de un análisis que procesó otra instancia.
        """
        local = super().ruta_archivo(analisis_id, nombre)
        if local is not None:
            return local
        if not self.activo or not id_valido(analisis_id) or nombre not in ARCHIVOS_A_SUBIR:
            return None

        destino = self.dir_analisis / analisis_id / nombre
        try:
            datos = self.sb.storage.from_(BUCKET).download(f"{analisis_id}/{nombre}")
        except Exception:  # noqa: BLE001
            return None
        if not datos:
            return None
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(datos)
        return destino

    def eliminar(self, analisis_id: str) -> bool:
        borrado_local = super().eliminar(analisis_id)
        if not self.activo or not id_valido(analisis_id):
            return borrado_local
        try:
            archivos = [f"{analisis_id}/{n}" for n in sorted(ARCHIVOS_A_SUBIR)]
            self.sb.storage.from_(BUCKET).remove(archivos)
            # zonas_metricas y eventos caen solos por ON DELETE CASCADE.
            self.sb.table("analisis").delete().eq("id", analisis_id).execute()
            return True
        except Exception as exc:  # noqa: BLE001
            print(f"[almacen] No se pudo eliminar {analisis_id} en Supabase: {exc}")
            return borrado_local

    # ── Consultas que solo tienen sentido con base de datos ───────────────

    def rendimiento_zonas(self, limite: int = 50) -> list[dict[str, Any]]:
        """Histórico agregado por góndola, a través de todos los análisis."""
        if not self.activo:
            return []
        try:
            return (
                self.sb.table("v_rendimiento_zona")
                .select("*")
                .order("visitas_totales", desc=True)
                .limit(limite)
                .execute()
                .data
                or []
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[almacen] Fallo en rendimiento por zona: {exc}")
            return []


def _tipo_mime(ruta: Path) -> str:
    return {
        ".png": "image/png",
        ".mp4": "video/mp4",
        ".json": "application/json",
        ".jsonl": "application/x-ndjson",
    }.get(ruta.suffix, "application/octet-stream")


def crear_historial(output_dir: Path | str) -> HistorialAnalisis:
    """
    Devuelve el historial adecuado según la configuración del entorno.

    Con SUPABASE_URL y SUPABASE_SERVICE_KEY definidas, se persiste en la nube;
    sin ellas, se cae al historial en disco de siempre. La API no tiene que
    saber cuál de los dos está usando.
    """
    almacen = HistorialSupabase(output_dir)
    if almacen.activo:
        print("[almacen] Persistencia en Supabase activa.")
        return almacen
    print("[almacen] Sin credenciales de Supabase: se usa el historial en disco.")
    return HistorialAnalisis(output_dir)
