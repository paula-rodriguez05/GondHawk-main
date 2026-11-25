"""
test_dwell_time.py
Tests del módulo tiempo de permanencia (GondHawk).

Cubre:
    1. Persona entra y sale antes del umbral → detuvo == False
    2. Persona permanece más que el umbral → detuvo == True
    3. Persona permanece exactamente el umbral → detuvo == True
    4. Persona entra en una zona y permanece hasta EOF → finalize calcula dwell
    5. Persona cambia de una zona a otra → cierra primera, abre segunda
    6. Dos personas simultáneamente en la misma zona
    7. Zona inválida sin vértices → error explícito
    8. person_id → track_id como string
    9. Centroide exactamente el punto medio del bbox
    10. frame_id NO es necesario para calcular dwell
"""

import json
from pathlib import Path
import sys
import tempfile

# Agregar src al path
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from trajectory_reader import TrajectoryReader
from dwell_time import (
    load_zones_from_json,
    DwellTimeAnalyzer,
    ZoneConfigError,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ZONE_1 = {
    "gondola_A1": {
        "name": "Góndola Test",
        "vertices": [[100, 50], [350, 50], [350, 450], [100, 450]],
    },
}


def track(person_id: int, bbox: list[float]) -> dict:
    return {"person_id": person_id, "bbox": bbox, "class": "person"}


# ---------------------------------------------------------------------------
# Escenarios
# ---------------------------------------------------------------------------

def test_entra_sale_antes_del_umbral():
    """1. Persona entra y sale antes del umbral → detuvo == False"""
    analyzer = DwellTimeAnalyzer(ZONE_1, min_dwell_ms=2000.0, grace_frames=0)
    bbox = [150.0, 100.0, 200.0, 150.0]  # centroide [175, 125] en zona

    analyzer.process_frame(0.0, [track(1, bbox)])
    analyzer.process_frame(500.0, [track(1, bbox)])   # 0.5s
    analyzer.process_frame(500.0, [])                  # sale

    events = analyzer.get_events()
    assert len(events) == 1, f"Se esperaba 1 evento, se obtuvieron {len(events)}"
    e = events[0]
    assert e["dwell_time_s"] < 2.0, f"dwell {e['dwell_time_s']} debería ser < 2s"
    assert e["detuvo"] is False, "debería ser detuvo=False"
    print(f"  ✓ detuvo=False, dwell={e['dwell_time_s']}s tienes < 2s")


def test_permanece_mas_del_umbral():
    """2. Persona permanece más que el umbral → detuvo == True"""
    analyzer = DwellTimeAnalyzer(ZONE_1, min_dwell_ms=2000.0, grace_frames=0)
    bbox = [150.0, 100.0, 200.0, 150.0]

    analyzer.process_frame(0.0, [track(1, bbox)])
    analyzer.process_frame(2500.0, [track(1, bbox)])  # 2.5s
    analyzer.process_frame(5000.0, [])                 # sale

    events = analyzer.get_events()
    assert len(events) == 1
    assert events[0]["detuvo"] is True, "debería ser detuvo=True"
    assert events[0]["dwell_time_s"] >= 2.0
    print(f"  ✓ detuvo=True, dwell={events[0]['dwell_time_s']}s >= 2s")


def test_permanece_exactamente_el_umbral():
    """3. Persona permanece exactamente el umbral → detuvo == True"""
    analyzer = DwellTimeAnalyzer(ZONE_1, min_dwell_ms=2000.0, grace_frames=0)
    bbox = [150.0, 100.0, 200.0, 150.0]

    analyzer.process_frame(0.0, [track(1, bbox)])
    analyzer.process_frame(2000.0, [track(1, bbox)])  # exactamente 2.0s
    analyzer.process_frame(4000.0, [])

    events = analyzer.get_events()
    assert len(events) == 1
    assert events[0]["detuvo"] is True, "umbral exacto debe ser detuvo=True (>=)"
    assert events[0]["dwell_time_s"] >= 2.0
    print(f"  ✓ umbral exacto (2.0s) → detuvo=True")


def test_permanece_hasta_eof():
    """4. Persona entra y permanece hasta EOF → finalize calcula el dwell"""
    analyzer = DwellTimeAnalyzer(ZONE_1, min_dwell_ms=2000.0, grace_frames=0)
    bbox = [150.0, 100.0, 200.0, 150.0]

    analyzer.process_frame(0.0, [track(1, bbox)])
    analyzer.process_frame(1000.0, [track(1, bbox)])
    # No hay más frames: persona sigue activa hasta EOF
    analyzer.finalize(3000.0)  # último timestamp disponible

    events = analyzer.get_events()
    assert len(events) == 1, "finalize() debería cerrar el track activo"
    e = events[0]
    assert e["dwell_time_s"] == 3.0, f"Se esperaba 3.0s, se obtuvo {e['dwell_time_s']}"
    assert e["timestamp_ms"] == 0.0, "timestamp_ms es el momento de entrada"
    print(f"  ✓ EOF: dwell={e['dwell_time_s']}s, detuvo={e['detuvo']}")


def test_cambia_de_zona():
    """5. Persona cambia de una zona a otra → cierra primera, abre segunda"""
    zones = {
        "gondola_A1": {"vertices": [[100, 50], [350, 50], [350, 450], [100, 450]]},
        "gondola_A2": {"vertices": [[400, 50], [650, 50], [650, 450], [400, 450]]},
    }
    analyzer = DwellTimeAnalyzer(zones, min_dwell_ms=2000.0, grace_frames=0)

    bbox_z1 = [150.0, 100.0, 200.0, 150.0]   # centroide [175,125] → z1
    bbox_z2 = [450.0, 100.0, 500.0, 150.0]   # centroide [475,125] → z2

    analyzer.process_frame(0.0, [track(1, bbox_z1)])
    analyzer.process_frame(1000.0, [track(1, bbox_z1)])
    analyzer.process_frame(1500.0, [track(1, bbox_z2)])  # cambia a z2
    analyzer.process_frame(2500.0, [track(1, bbox_z2)])
    analyzer.process_frame(4000.0, [])

    events = analyzer.get_events()
    assert len(events) == 2, f"Se esperaban 2 eventos, se obtuvieron {len(events)}"

    e1 = next(e for e in events if e["zone_id"] == "gondola_A1")
    e2 = next(e for e in events if e["zone_id"] == "gondola_A2")

    assert e1["timestamp_ms"] == 0.0 and e1["dwell_time_s"] == 1.5, "z1 0→1.5s"
    assert e1["detuvo"] is False, "z1 1.5s debe ser detuvo=False"
    assert e2["timestamp_ms"] == 1500.0, "z2 entró en 1500ms"
    assert e2["dwell_time_s"] == 2.5, "z2 1500→4000 = 2.5s"
    assert e2["detuvo"] is True, "z2 2.5s debe ser detuvo=True"
    print("  ✓ cambio de zona: cierra z1 (1.5s) y abre z2 (2.5s)")


def test_dos_personas_misma_zona():
    """6. Dos personas simultáneamente en la misma zona"""
    analyzer = DwellTimeAnalyzer(ZONE_1, min_dwell_ms=2000.0, grace_frames=0)
    bbox = [150.0, 100.0, 200.0, 150.0]

    analyzer.process_frame(0.0, [track(1, bbox), track(2, bbox)])
    analyzer.process_frame(1000.0, [track(1, bbox), track(2, bbox)])
    analyzer.process_frame(3000.0, [])

    events = analyzer.get_events()
    assert len(events) == 2, "Se deben generar 2 eventos (uno por persona)"
    ids = {e["track_id"] for e in events}
    assert ids == {"1", "2"}, f"track_ids incorrectos: {ids}"
    for e in events:
        assert e["dwell_time_s"] == 3.0
        assert e["detuvo"] is True
    print("  ✓ dos personas simultáneas: 2 eventos, detuvo=True")


def test_zona_invalida_sin_vertices():
    """7. Zona inválida sin vértices → error explícito"""
    zones_mal = {
        "gondola_bad": {"name": "Zona sin vértices"},
    }
    try:
        DwellTimeAnalyzer(zones_mal)
    except ZoneConfigError as exc:
        assert "gondola_bad" in str(exc), f"Mensaje debe nombrar la zona: {exc}"
        print(f"  ✓ error explícito para zona sin vértices: {exc}")
        return
    raise AssertionError("Debería haber lanzado ZoneConfigError")


def test_track_id_string():
    """8. person_id debe convertirse a string en track_id"""
    analyzer = DwellTimeAnalyzer(ZONE_1, min_dwell_ms=0.0, grace_frames=0)
    bbox = [150.0, 100.0, 200.0, 150.0]
    analyzer.process_frame(0.0, [track(42, bbox)])
    analyzer.process_frame(1000.0, [])
    e = analyzer.get_events()[0]
    assert e["track_id"] == "42", f"track_id debe ser '42', se obtuvo {e['track_id']!r}"
    assert isinstance(e["track_id"], str), "track_id debe ser string"
    print(f"  ✓ track_id='42' (string), type={type(e['track_id']).__name__}")


def test_centroide_punto_medio():
    """9. Centroide debe ser exactamente el punto medio del bbox"""
    bbox = [100.0, 50.0, 200.0, 150.0]
    centroid = TrajectoryReader.get_centroid(bbox)
    assert centroid[0] == 150.0, f"center_x esperado 150, se obtuvo {centroid[0]}"
    assert centroid[1] == 100.0, f"center_y esperado 100, se obtuvo {centroid[1]}"
    print(f"  ✓ centroide punto medio: ({centroid[0]}, {centroid[1]})")


def test_frame_id_no_necesario():
    """10. frame_id NO es necesario para calcular dwell"""
    # El procesamiento usa solo timestamp_ms; process_frame NO recibe frame_id.
    analyzer = DwellTimeAnalyzer(ZONE_1, min_dwell_ms=2000.0, grace_frames=0)
    bbox = [150.0, 100.0, 200.0, 150.0]

    # Llamamos process_frame sin frame_id (solo timestamp + tracks)
    analyzer.process_frame(0.0, [track(1, bbox)])
    analyzer.process_frame(1000.0, [track(1, bbox)])
    analyzer.process_frame(3000.0, [])

    events = analyzer.get_events()
    assert len(events) == 1
    assert events[0]["dwell_time_s"] == 3.0, (
        "dwell calculado solo con timestamp_ms, sin frame_id"
    )
    print("  ✓ frame_id NO participa: dwell=3.0s calculado solo con timestamp_ms")


def test_grace_frames_toleran_oclusion_transitoria():
    """Grace frames: la oclusión breve no cierra el evento si reaparece antes del umbral."""
    analyzer = DwellTimeAnalyzer(ZONE_1, min_dwell_ms=1000.0, grace_frames=2)
    bbox = [150.0, 100.0, 200.0, 150.0]

    analyzer.process_frame(0.0, [track(1, bbox)])
    analyzer.process_frame(1000.0, [track(1, bbox)])
    analyzer.process_frame(1500.0, [])
    analyzer.process_frame(2000.0, [track(1, bbox)])
    analyzer.process_frame(2500.0, [track(1, bbox)])
    analyzer.process_frame(3000.0, [])
    analyzer.process_frame(3500.0, [])

    events = analyzer.get_events()
    assert len(events) == 1, f"Se esperaba 1 evento, se obtuvieron {len(events)}"
    e = events[0]
    assert e["track_id"] == "1"
    assert e["zone_id"] == "gondola_A1"
    assert e["dwell_time_s"] == 3.5, f"Se esperaba 3.5s, se obtuvo {e['dwell_time_s']}"
    assert e["detuvo"] is True
    print("  ✓ gracia de frames: la oclusión breve se tolera y el dwell continúa")


# ---------------------------------------------------------------------------
# Validaciones adicionales (estructura/Errores)
# ---------------------------------------------------------------------------

def test_firma_process_frame_sin_frame_id():
    """Verifica que process_frame NO acepta frame_id (solo timestamp, tracks)."""
    import inspect
    from dwell_time import DwellTimeAnalyzer

    sig = inspect.signature(DwellTimeAnalyzer.process_frame)
    params = list(sig.parameters.keys())
    assert "frame_id" not in params, f"process_frame no debe recibir frame_id: {params}"
    assert params == ["self", "timestamp_ms", "tracks"], (
        f"Firma inesperada: {params}"
    )
    print(f"  ✓ process_frame firma: process_frame({', '.join(params[1:])})")


def test_load_zones():
    """Cargar el catálogo unificado de zonas del proyecto."""
    zones_path = Path(__file__).resolve().parents[1] / "mapas_de_calor" / "config" / "zonas.json"
    assert zones_path.exists(), f"No existe el catálogo oficial: {zones_path}"

    zones = load_zones_from_json(zones_path)
    assert zones, "No se cargaron zonas"

    print(f"✓ Zonas cargadas: {len(zones)}")
    for zone_id in zones:
        print(f"  - {zone_id}")


def test_trajectory_reader():
    """TrajectoryReader con datos sintéticos + validación de track_id"""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".jsonl", delete=False
    ) as f:
        frames = [
            {
                "frame_id": 0,
                "timestamp_ms": 0.0,
                "tracks": [track(1, [100, 50, 200, 150])],
            },
            {
                "frame_id": 1,
                "timestamp_ms": 100.0,
                "tracks": [track(1, [102, 52, 202, 152])],
            },
        ]
        for frame in frames:
            f.write(json.dumps(frame) + "\n")
        temp_path = Path(f.name)

    try:
        reader = TrajectoryReader(temp_path)
        records = reader.read_all()
        assert len(records) == 2, f"Se esperaban 2 frames, se obtuvieron {len(records)}"

        # track_id como string
        tid = TrajectoryReader.get_track_id(1)
        assert tid == "1" and isinstance(tid, str)
        print(f"✓ TrajectoryReader: {len(records)} frames, track_id='{tid}'")
    finally:
        temp_path.unlink()


def test_output_format_contracto():
    """Verifica que la salida cumpla EXACTAMENTE el contrato del backend."""
    required_fields = ["track_id", "zone_id", "dwell_time_s", "timestamp_ms", "detuvo"]
    allowed_fields = set(required_fields)

    analyzer = DwellTimeAnalyzer(ZONE_1, min_dwell_ms=1000.0, grace_frames=0)
    bbox = [150.0, 100.0, 200.0, 150.0]
    # Persona 1: entra 0ms, sale 800ms → dwell 0.8s → detuvo=False
    analyzer.process_frame(0.0, [track(1, bbox)])
    analyzer.process_frame(400.0, [track(1, bbox), track(2, bbox)])
    analyzer.process_frame(800.0, [track(2, bbox)])  # persona 1 sale aquí (0.8s)
    analyzer.process_frame(4000.0, [track(2, bbox)])  # persona 2 sigue (2000+ms desde 400)
    analyzer.process_frame(6000.0, [])  # persona 2 sale → dwell 400→6000=5.6s

    events = analyzer.get_events()
    assert len(events) == 2

    tipos = {"track_id": str, "zone_id": str, "dwell_time_s": float,
             "timestamp_ms": (int, float), "detuvo": bool}
    detuvo_values = set()

    for e in events:
        assert set(e.keys()) == allowed_fields, (
            f"Campos del evento no coinciden con el contrato: {set(e.keys())}"
        )
        for field, tipo in tipos.items():
            assert isinstance(e[field], tipo), (
                f"{field} debe ser {tipo}, se obtuvo {type(e[field])} en {e[field]!r}"
            )
        detuvo_values.add(e["detuvo"])

    # Debe haber eventos con detuvo=True y False tras el cambio
    assert detuvo_values == {True, False}, (
        "Debe haber registros con detuvo=True y detuvo=False"
    )
    print(f"  ✓ Contrato exacto + coexisten detuvo=True/False: {sorted(detuvo_values)}")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("TESTS - Módulo Tiempo de Permanencia (Refactorizado)")
    print("=" * 60)

    tests = [
        ("Entra y sale antes del umbral (detuvo=false)",
         test_entra_sale_antes_del_umbral),
        ("Permanece más del umbral (detuvo=true)",
         test_permanece_mas_del_umbral),
        ("Permanece exactamente el umbral (detuvo=true)",
         test_permanece_exactamente_el_umbral),
        ("Permanece hasta EOF (finalize)",
         test_permanece_hasta_eof),
        ("Cambia de una zona a otra",
         test_cambia_de_zona),
        ("Dos personas simultáneas en la misma zona",
         test_dos_personas_misma_zona),
        ("Zona inválida sin vértices (error explícito)",
         test_zona_invalida_sin_vertices),
        ("track_id como string",
         test_track_id_string),
        ("Centroide punto medio del bbox",
         test_centroide_punto_medio),
        ("frame_id NO necesario para dwell",
         test_frame_id_no_necesario),
        ("grace frames toleran oclusión transitoria",
         test_grace_frames_toleran_oclusion_transitoria),
        ("process_frame sin frame_id (firma)",
         test_firma_process_frame_sin_frame_id),
        ("Cargar zonas.json",
         test_load_zones),
        ("TrajectoryReader y track_id",
         test_trajectory_reader),
        ("Formato de salida cumple contrato + detuvo True/False",
         test_output_format_contracto),
    ]

    passed = 0
    failed = 0

    for name, test_func in tests:
        print(f"\n▶ {name}")
        try:
            # Un test pasa si no lanza AssertionError. Antes esto era
            # "if test_func():", pero las funciones de test no retornan nada:
            # devolvían None y las 15 se reportaban como FAILED aunque todas
            # sus assertions pasaran.
            test_func()
            passed += 1
            print("  PASSED")
        except Exception as e:
            failed += 1
            print(f"  ERROR: {type(e).__name__}: {e}")
            import traceback

            traceback.print_exc()

    print("\n" + "=" * 60)
    print(f"Resultados: {passed} passed, {failed} failed")
    print("=" * 60)

    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
