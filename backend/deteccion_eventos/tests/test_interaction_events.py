"""
test_interaction_events.py
Suite de pruebas del Modulo 1 — GondHawk.

Ejecutar desde la raiz del proyecto:

    python deteccion_eventos/tests/test_interaction_events.py

Cubre: geometria de zonas, deteccion de alcance con histeresis, las
transiciones de la maquina de estados (pass_by, approach, pickup, return,
takeaway), la tolerancia a oclusiones, el cruce con el modulo 5 y la
proyeccion al esquema del validador del modulo 8.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))

from metrics import DwellIndex, calcular_metricas  # noqa: E402
from reach_detector import (  # noqa: E402
    GeometricReachDetector,
    PoseReachDetector,
    ReachConfig,
    crear_detector,
)
from run_events import a_iso, proyectar_compliance  # noqa: E402
from state_machine import (  # noqa: E402
    Estado,
    InteractionConfig,
    InteractionStateMachine,
)
from zonas import Layout, Zona, ZonaError, cargar_layout, centroide_bbox  # noqa: E402

FPS = 10.0
DT_MS = 1000.0 / FPS


def layout_prueba() -> Layout:
    return Layout(
        [
            Zona("gondola_A1", [(0, 0), (100, 0), (100, 100), (0, 100)]),
            Zona("gondola_A2", [(200, 0), (300, 0), (300, 100), (200, 100)]),
            Zona("pasillo_central", [(0, 200), (300, 200), (300, 260), (0, 260)]),
        ]
    )


def bbox_en(x: float, y: float, ancho: float = 40.0, alto: float = 90.0) -> list[float]:
    return [x - ancho / 2, y - alto / 2, x + ancho / 2, y + alto / 2]


def correr(
    guion: list[tuple[float, list[dict]]],
    layout: Layout | None = None,
    config: InteractionConfig | None = None,
    reach_config: ReachConfig | None = None,
) -> InteractionStateMachine:
    maquina = InteractionStateMachine(
        layout or layout_prueba(),
        config=config or InteractionConfig(min_dwell_s=2.0, gracia_frames=5),
        reach_config=reach_config,
    )
    ts = 0.0
    for ts, tracks in guion:
        maquina.process_frame(ts, tracks)
    maquina.finalize(ts)
    return maquina


def guion_simple(
    person_id: int,
    frames: list[tuple[float, float, float]],
    inicio_ms: float = 0.0,
) -> list[tuple[float, list[dict]]]:
    """frames = [(x, y, ancho), ...] a 10 fps."""
    salida = []
    for i, (x, y, ancho) in enumerate(frames):
        salida.append(
            (
                inicio_ms + i * DT_MS,
                [{"person_id": person_id, "bbox": bbox_en(x, y, ancho), "class": "person"}],
            )
        )
    return salida


def tipos(maquina: InteractionStateMachine) -> list[str]:
    return [e.event_type for e in maquina.eventos]


class TestGeometria(unittest.TestCase):
    def test_punto_dentro_y_fuera(self):
        zona = Zona("z", [(0, 0), (10, 0), (10, 10), (0, 10)])
        self.assertTrue(zona.contiene(5, 5))
        self.assertFalse(zona.contiene(15, 5))

    def test_borde_cuenta_como_dentro(self):
        zona = Zona("z", [(0, 0), (10, 0), (10, 10), (0, 10)])
        self.assertTrue(zona.contiene(0, 5))
        self.assertTrue(zona.contiene(10, 10))

    def test_poligono_concavo(self):
        # Forma de L: el hueco no debe contar como dentro
        zona = Zona(
            "L", [(0, 0), (10, 0), (10, 4), (4, 4), (4, 10), (0, 10)]
        )
        self.assertTrue(zona.contiene(2, 8))
        self.assertFalse(zona.contiene(8, 8))

    def test_menos_de_tres_vertices_falla(self):
        with self.assertRaises(ZonaError):
            Zona("z", [(0, 0), (1, 1)])

    def test_centroide_es_punto_medio_del_bbox(self):
        self.assertEqual(centroide_bbox([10, 20, 30, 60]), (20.0, 40.0))

    def test_gondola_gana_sobre_pasillo_en_solape(self):
        layout = Layout(
            [
                Zona("pasillo_central", [(0, 0), (100, 0), (100, 100), (0, 100)]),
                Zona("gondola_A1", [(40, 40), (60, 40), (60, 60), (40, 60)]),
            ]
        )
        self.assertEqual(layout.zona_de_punto(50, 50).zone_id, "gondola_A1")
        self.assertEqual(layout.zona_de_punto(10, 10).zone_id, "pasillo_central")

    def test_carga_los_dos_esquemas_de_zonas_json(self):
        esquema_a = {
            "zonas": [
                {"zone_id": "gondola_A1", "poligono": [[0, 0], [10, 0], [10, 10]]}
            ]
        }
        esquema_b = {
            "zones": {
                "gondola_1": {
                    "name": "Gondola frente",
                    "vertices": [[0, 0], [10, 0], [10, 10]],
                }
            }
        }
        with tempfile.TemporaryDirectory() as tmp:
            for nombre, data in (("a.json", esquema_a), ("b.json", esquema_b)):
                ruta = Path(tmp) / nombre
                ruta.write_text(json.dumps(data), encoding="utf-8")
                layout = cargar_layout(ruta)
                self.assertEqual(len(layout), 1)
                self.assertTrue(layout.gondolas)

    def test_zonas_json_invalido_falla_explicito(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta = Path(tmp) / "x.json"
            ruta.write_text(json.dumps({"otra_cosa": []}), encoding="utf-8")
            with self.assertRaises(ZonaError):
                cargar_layout(ruta)


class TestDetectorAlcance(unittest.TestCase):
    def _alimentar(self, detector, anchos, alto=90.0):
        resultados = []
        for i, ancho in enumerate(anchos):
            r = detector.update(
                "1", {"bbox": [0, 0, ancho, alto]}, i * DT_MS
            )
            if r is not None:
                resultados.append(r)
        return resultados

    def test_detecta_alcance_claro(self):
        detector = GeometricReachDetector()
        anchos = [40] * 10 + [58] * 8 + [40] * 5
        reaches = self._alimentar(detector, anchos)
        self.assertEqual(len(reaches), 1)
        self.assertTrue(reaches[0].valido)
        self.assertGreater(reaches[0].confianza, 0.5)

    def test_ignora_bbox_estable(self):
        detector = GeometricReachDetector()
        self.assertEqual(self._alimentar(detector, [40] * 30), [])

    def test_es_invariante_a_la_escala(self):
        # La persona se acerca a la camara: w y h crecen juntos, no es alcance.
        detector = GeometricReachDetector()
        resultados = []
        for i in range(30):
            escala = 1.0 + i * 0.05
            r = detector.update(
                "1", {"bbox": [0, 0, 40 * escala, 90 * escala]}, i * DT_MS
            )
            if r is not None:
                resultados.append(r)
        self.assertEqual([r for r in resultados if r.valido], [])

    def test_descarta_alcance_de_un_solo_frame(self):
        detector = GeometricReachDetector()
        reaches = self._alimentar(detector, [40] * 10 + [58] + [40] * 5)
        self.assertTrue(all(not r.valido for r in reaches))

    def test_descarta_alcance_demasiado_largo(self):
        detector = GeometricReachDetector(ReachConfig(max_duracion_ms=1000.0))
        reaches = self._alimentar(detector, [40] * 10 + [58] * 30 + [40] * 5)
        self.assertTrue(reaches)
        self.assertFalse(reaches[0].valido)
        self.assertIn("maximo", reaches[0].motivo_descarte)

    def test_histeresis_no_duplica_eventos(self):
        # Oscila alrededor del umbral de entrada sin bajar del de salida:
        # debe seguir siendo UN solo alcance.
        detector = GeometricReachDetector()
        anchos = [40] * 10 + [58, 50, 57, 51, 58] + [40] * 5
        reaches = [r for r in self._alimentar(detector, anchos) if r.valido]
        self.assertEqual(len(reaches), 1)

    def test_alcance_sin_cierre_se_marca_invalido(self):
        detector = GeometricReachDetector()
        self._alimentar(detector, [40] * 10 + [58] * 8)
        pendiente = detector.cerrar("1", 2000.0)
        self.assertIsNotNone(pendiente)
        self.assertFalse(pendiente.valido)

    def test_detector_pose_usa_keypoints(self):
        detector = PoseReachDetector()
        kps_reposo = [[0, 0, 0]] * 13
        kps_reposo[5] = [100, 100, 0.9]   # hombro izq
        kps_reposo[6] = [140, 100, 0.9]   # hombro der
        kps_reposo[9] = [100, 130, 0.9]   # muneca izq (brazo abajo)
        kps_reposo[10] = [140, 130, 0.9]
        kps_reposo[11] = [105, 180, 0.9]  # cadera izq
        kps_reposo[12] = [135, 180, 0.9]

        kps_alcance = [list(k) for k in kps_reposo]
        kps_alcance[10] = [230, 100, 0.9]  # muneca der extendida

        resultados = []
        for i in range(12):
            r = detector.update("1", {"keypoints": kps_reposo}, i * DT_MS)
            if r:
                resultados.append(r)
        for i in range(12, 20):
            r = detector.update("1", {"keypoints": kps_alcance}, i * DT_MS)
            if r:
                resultados.append(r)
        for i in range(20, 26):
            r = detector.update("1", {"keypoints": kps_reposo}, i * DT_MS)
            if r:
                resultados.append(r)

        validos = [r for r in resultados if r.valido]
        self.assertEqual(len(validos), 1)

    def test_fabrica_de_detectores(self):
        self.assertEqual(crear_detector("geometrico").nombre, "geometrico")
        self.assertEqual(crear_detector("pose").nombre, "pose")
        with self.assertRaises(ValueError):
            crear_detector("telepatia")


class TestMaquinaEstados(unittest.TestCase):
    def test_pasa_de_largo_genera_pass_by(self):
        # 1 s dentro de la gondola: por debajo del umbral de 2 s
        guion = guion_simple(1, [(50, 50, 40)] * 10 + [(250, 230, 40)] * 3)
        maquina = correr(guion)
        self.assertIn("pass_by", tipos(maquina))
        self.assertNotIn("approach", tipos(maquina))

    def test_se_detiene_genera_approach(self):
        guion = guion_simple(1, [(50, 50, 40)] * 40)
        maquina = correr(guion)
        self.assertEqual(tipos(maquina).count("approach"), 1)

    def test_pickup_y_takeaway(self):
        recorrido = (
            [(50, 50, 40)] * 30      # se detiene
            + [(50, 50, 58)] * 8     # estira el brazo
            + [(50, 50, 40)] * 8     # lo baja
            + [(250, 230, 40)] * 8   # se va al pasillo
        )
        maquina = correr(guion_simple(1, recorrido))
        self.assertEqual(tipos(maquina), ["approach", "pickup", "takeaway"])

    def test_pickup_seguido_de_return(self):
        recorrido = (
            [(50, 50, 40)] * 30
            + [(50, 50, 58)] * 8     # toma
            + [(50, 50, 40)] * 15
            + [(50, 50, 58)] * 8     # devuelve
            + [(50, 50, 40)] * 8
            + [(250, 230, 40)] * 8
        )
        maquina = correr(guion_simple(1, recorrido))
        self.assertEqual(tipos(maquina), ["approach", "pickup", "return"])
        self.assertNotIn("takeaway", tipos(maquina))

    def test_dos_pickups_alternados_dan_pickup_return_pickup(self):
        recorrido = (
            [(50, 50, 40)] * 30
            + [(50, 50, 58)] * 8
            + [(50, 50, 40)] * 12
            + [(50, 50, 58)] * 8
            + [(50, 50, 40)] * 12
            + [(50, 50, 58)] * 8
            + [(50, 50, 40)] * 8
            + [(250, 230, 40)] * 8
        )
        maquina = correr(guion_simple(1, recorrido))
        self.assertEqual(
            tipos(maquina), ["approach", "pickup", "return", "pickup", "takeaway"]
        )

    def test_alcance_antes_del_umbral_emite_approach_primero(self):
        # El embudo no puede tener un pickup sin approach previo.
        recorrido = (
            [(50, 50, 40)] * 8       # menos de 2 s
            + [(50, 50, 58)] * 6
            + [(50, 50, 40)] * 4
            + [(250, 230, 40)] * 8
        )
        maquina = correr(guion_simple(1, recorrido))
        self.assertEqual(tipos(maquina)[:2], ["approach", "pickup"])

    def test_oclusion_corta_no_fragmenta_el_episodio(self):
        guion = guion_simple(1, [(50, 50, 40)] * 20)
        # 3 frames sin ninguna deteccion (por debajo de gracia_frames=5)
        for i in range(3):
            guion.append((20 * DT_MS + i * DT_MS, []))
        guion += guion_simple(1, [(50, 50, 40)] * 20, inicio_ms=23 * DT_MS)
        maquina = correr(guion)
        self.assertEqual(tipos(maquina).count("approach"), 1)

    def test_ausencia_larga_cierra_el_episodio(self):
        guion = guion_simple(1, [(50, 50, 40)] * 30)
        for i in range(10):
            guion.append((30 * DT_MS + i * DT_MS, []))
        guion += guion_simple(1, [(50, 50, 40)] * 30, inicio_ms=40 * DT_MS)
        maquina = correr(guion)
        self.assertEqual(tipos(maquina).count("approach"), 2)

    def test_cambio_de_gondola_cierra_y_abre_episodio(self):
        recorrido = [(50, 50, 40)] * 30 + [(250, 50, 40)] * 30
        maquina = correr(guion_simple(1, recorrido))
        zonas = [(e.zone_id, e.event_type) for e in maquina.eventos]
        self.assertIn(("gondola_A1", "approach"), zonas)
        self.assertIn(("gondola_A2", "approach"), zonas)

    def test_pasillo_no_genera_eventos(self):
        maquina = correr(guion_simple(1, [(150, 230, 40)] * 40))
        self.assertEqual(maquina.eventos, [])

    def test_dos_personas_simultaneas_no_se_mezclan(self):
        guion = []
        for i in range(40):
            ts = i * DT_MS
            ancho_p2 = 58 if 30 <= i < 38 else 40
            guion.append(
                (
                    ts,
                    [
                        {"person_id": 1, "bbox": bbox_en(50, 50, 40), "class": "person"},
                        {
                            "person_id": 2,
                            "bbox": bbox_en(250, 50, ancho_p2),
                            "class": "person",
                        },
                    ],
                )
            )
        maquina = correr(guion)
        por_track = {}
        for e in maquina.eventos:
            por_track.setdefault(e.track_id, []).append(e.event_type)
        self.assertEqual(por_track["1"], ["approach"])
        self.assertIn("pickup", por_track["2"])

    def test_track_id_es_string_de_person_id(self):
        maquina = correr(guion_simple(7, [(50, 50, 40)] * 30))
        self.assertTrue(all(isinstance(e.track_id, str) for e in maquina.eventos))
        self.assertEqual(maquina.eventos[0].track_id, "7")

    def test_clase_distinta_de_person_se_ignora(self):
        guion = [
            (
                i * DT_MS,
                [{"person_id": 1, "bbox": bbox_en(50, 50), "class": "carrito"}],
            )
            for i in range(40)
        ]
        maquina = correr(guion)
        self.assertEqual(maquina.eventos, [])

    def test_track_sin_bbox_falla_explicito(self):
        maquina = InteractionStateMachine(layout_prueba())
        with self.assertRaises(ValueError):
            maquina.process_frame(0.0, [{"person_id": 1, "class": "person"}])

    def test_finalize_cierra_episodio_abierto(self):
        maquina = correr(guion_simple(1, [(50, 50, 40)] * 8))
        self.assertIn("pass_by", tipos(maquina))

    def test_estado_se_libera_al_cerrar_episodio(self):
        recorrido = [(50, 50, 40)] * 30 + [(250, 230, 40)] * 20
        maquina = correr(guion_simple(1, recorrido))
        self.assertEqual(maquina.episodios, {})


class TestMetricas(unittest.TestCase):
    def _maquina_mixta(self) -> InteractionStateMachine:
        guion = []
        # persona 1: toma y se lleva
        guion += guion_simple(
            1, [(50, 50, 40)] * 30 + [(50, 50, 58)] * 8 + [(50, 50, 40)] * 6
            + [(250, 230, 40)] * 6
        )
        # persona 2: pasa de largo por la misma gondola
        guion += guion_simple(2, [(50, 50, 40)] * 8 + [(250, 230, 40)] * 6, inicio_ms=6000)
        return correr(guion)

    def test_embudo_por_zona(self):
        maquina = self._maquina_mixta()
        metricas = calcular_metricas(maquina.eventos, ["gondola_A1", "gondola_A2"])
        a1 = next(z for z in metricas["zonas"] if z["zone_id"] == "gondola_A1")
        self.assertEqual(a1["embudo"]["visitas"], 2)
        self.assertEqual(a1["embudo"]["se_detiene"], 1)
        self.assertEqual(a1["embudo"]["toma_producto"], 1)
        self.assertEqual(a1["embudo"]["se_lo_lleva"], 1)
        self.assertEqual(a1["tasa_interaccion"], 1.0)

    def test_zona_sin_datos_aparece_en_el_tablero(self):
        maquina = self._maquina_mixta()
        metricas = calcular_metricas(maquina.eventos, ["gondola_A1", "gondola_A2"])
        a2 = next(z for z in metricas["zonas"] if z["zone_id"] == "gondola_A2")
        self.assertEqual(a2["temperatura"], "sin_datos")

    def test_tasa_de_rechazo(self):
        recorrido = (
            [(50, 50, 40)] * 30
            + [(50, 50, 58)] * 8
            + [(50, 50, 40)] * 15
            + [(50, 50, 58)] * 8
            + [(50, 50, 40)] * 6
            + [(250, 230, 40)] * 6
        )
        maquina = correr(guion_simple(1, recorrido))
        metricas = calcular_metricas(maquina.eventos, ["gondola_A1"])
        self.assertEqual(metricas["total"]["tasa_rechazo"], 1.0)

    def test_sin_division_por_cero(self):
        metricas = calcular_metricas([], ["gondola_A1"])
        self.assertEqual(metricas["total"]["tasa_interaccion"], 0.0)
        self.assertEqual(metricas["total"]["tasa_rechazo"], 0.0)


class TestCruceModulo5(unittest.TestCase):
    def test_encuentra_el_episodio_que_cubre_el_instante(self):
        indice = DwellIndex(
            [
                {"track_id": "1", "zone_id": "gondola_A1", "dwell_time_s": 5.0,
                 "timestamp_ms": 1000.0, "detuvo": True},
            ]
        )
        cruce = indice.buscar("1", "gondola_A1", 3000.0)
        self.assertIsNotNone(cruce)
        self.assertEqual(cruce["dwell_time_s"], 5.0)

    def test_tolerancia_de_un_segundo_por_fragmentacion(self):
        indice = DwellIndex(
            [
                {"track_id": "1", "zone_id": "gondola_A1", "dwell_time_s": 2.0,
                 "timestamp_ms": 1000.0, "detuvo": True},
            ]
        )
        self.assertIsNotNone(indice.buscar("1", "gondola_A1", 3500.0))
        self.assertIsNone(indice.buscar("1", "gondola_A1", 9000.0))

    def test_sin_archivo_de_dwell_no_rompe(self):
        indice = DwellIndex.desde_archivo(None)
        self.assertEqual(len(indice), 0)
        self.assertIsNone(indice.buscar("1", "gondola_A1", 0.0))


class TestCompliance(unittest.TestCase):
    """El esquema que exige el validador del modulo 8 (Paula)."""

    CAMPOS_PERMITIDOS = {
        "track_id", "zone_id", "product_id", "event_type",
        "dwell_time_s", "timestamp", "bbox",
    }
    EVENT_TYPES_VALIDOS = {"approach", "pickup", "return", "pass_by"}

    def _eventos(self):
        recorrido = (
            [(50, 50, 40)] * 30
            + [(50, 50, 58)] * 8
            + [(50, 50, 40)] * 15
            + [(50, 50, 58)] * 8
            + [(50, 50, 40)] * 6
            + [(250, 230, 40)] * 6
        )
        return correr(guion_simple(1, recorrido)).eventos

    def test_solo_campos_permitidos(self):
        t0 = datetime(2026, 8, 20, 9, 0, 0)
        for evento in self._eventos():
            registro = proyectar_compliance(evento, t0, {"gondola_A1": "SKU_1001_snacks"})
            if registro is None:
                continue
            self.assertTrue(set(registro).issubset(self.CAMPOS_PERMITIDOS))

    def test_solo_tipos_de_evento_acordados(self):
        t0 = datetime(2026, 8, 20, 9, 0, 0)
        for evento in self._eventos():
            registro = proyectar_compliance(evento, t0, {})
            if registro is not None:
                self.assertIn(registro["event_type"], self.EVENT_TYPES_VALIDOS)

    def test_takeaway_no_se_exporta(self):
        recorrido = (
            [(50, 50, 40)] * 30 + [(50, 50, 58)] * 8 + [(50, 50, 40)] * 6
            + [(250, 230, 40)] * 6
        )
        eventos = correr(guion_simple(1, recorrido)).eventos
        self.assertIn("takeaway", [e.event_type for e in eventos])
        t0 = datetime(2026, 8, 20, 9, 0, 0)
        exportados = [
            e for e in eventos if proyectar_compliance(e, t0, {}) is not None
        ]
        self.assertNotIn("takeaway", [e.event_type for e in exportados])

    def test_timestamp_es_iso_parseable(self):
        t0 = datetime(2026, 8, 20, 9, 0, 0)
        iso = a_iso(t0, 90_000.0)
        self.assertEqual(datetime.fromisoformat(iso), datetime(2026, 8, 20, 9, 1, 30))

    def test_dwell_time_es_numero_no_negativo(self):
        t0 = datetime(2026, 8, 20, 9, 0, 0)
        for evento in self._eventos():
            registro = proyectar_compliance(evento, t0, {})
            if registro is not None:
                self.assertIsInstance(registro["dwell_time_s"], float)
                self.assertGreaterEqual(registro["dwell_time_s"], 0.0)

    def test_product_id_respeta_el_patron_sku(self):
        t0 = datetime(2026, 8, 20, 9, 0, 0)
        registro = proyectar_compliance(
            self._eventos()[0], t0, {"gondola_A1": "SKU_1001_snacks"}
        )
        self.assertTrue(registro["product_id"].startswith("SKU_"))

    def test_track_id_pasa_el_regex_hexadecimal(self):
        import re

        patron = re.compile(r"^[0-9a-fA-F]{1,8}(-[0-9a-fA-F]{1,12}){0,4}$")
        t0 = datetime(2026, 8, 20, 9, 0, 0)
        registro = proyectar_compliance(self._eventos()[0], t0, {})
        self.assertTrue(patron.match(registro["track_id"]))

    def test_no_se_exporta_bbox(self):
        """Minimizacion de datos: el bbox esta permitido pero no se necesita."""
        t0 = datetime(2026, 8, 20, 9, 0, 0)
        registro = proyectar_compliance(self._eventos()[0], t0, {})
        self.assertNotIn("bbox", registro)


if __name__ == "__main__":
    unittest.main(verbosity=2)
