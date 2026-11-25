"""
zonas_auto.py
Propuesta automática de zonas a partir del video — GondHawk.

Resuelve el problema que hace que todas las métricas den cero cuando se sube un
video nuevo: `zonas.json` está dibujado sobre otro video, así que los polígonos
caen donde no hay góndolas. Escalarlos arregla la proporción pero no la
ubicación — para eso hay que mirar ESTE video.

Este módulo propone zonas a partir de dos fuentes de evidencia:

1. ESTRUCTURA (dónde hay estantería)
   Las góndolas producen bordes verticales largos y regulares, bordes
   horizontales repetidos (entrepaños) y color saturado (producto empacado).
   Se calcula un puntaje de "estanteria" por celda de una rejilla.

2. TRÁNSITO (por dónde camina la gente)
   Si ya existe un `tracking.jsonl`, las celdas por donde pasan las personas
   son pasillo, no estante: nadie camina a través de una góndola. Esta señal
   es la que más discrimina, porque corrige los falsos positivos de la
   estructura (una pared con azulejos también tiene líneas).

De la combinación salen tres tipos de zona:
    gondola_*         estructura alta, tránsito bajo
    pasillo_*         tránsito alto
    caja_*            estructura alta y tránsito alto, en el borde inferior
                      del frame — el punto de pago es lo único que combina
                      mueble y gente parada encima. Distinguirla importa
                      porque una caja NO es una góndola: si se cuenta como
                      tal, la fila de pago se lee como interacción con
                      producto e infla la tasa de interacción.

IMPORTANTE, y hay que decirlo en la sustentación: esto es una PROPUESTA que el
operador revisa, no una definición automática de confianza ciega. La salida
incluye un puntaje por zona; lo correcto es abrir `zone_definer.py` y ajustar.
Un layout mal definido produce métricas que parecen válidas y no lo son, que es
el peor error posible en este sistema.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np

# Rejilla de análisis. 12x9 sobre 768x576 da celdas de 64x64 px: suficientemente
# fino para separar una góndola de un pasillo, suficientemente grueso para que
# el ruido de un frame no mueva la clasificación.
COLUMNAS = 12
FILAS = 9

# Ancho máximo (en celdas) de una góndola individual. Sin tránsito que separe
# dos góndolas contiguas (o con tránsito escaso), _agrupar() las fusiona en un
# único bloque conexo: por eso el mapa terminaba mostrando "una sola góndola"
# aunque hubiera varias en fila. Se corta cualquier bloque de estructura más
# ancho que esto en módulos independientes, que es el tamaño típico de una
# góndola real dentro de la rejilla de 12 columnas.
MAX_ANCHO_GONDOLA_CELDAS = 3


def _puntaje_estructura(frames: list[np.ndarray]) -> np.ndarray:
    """Puntaje de 'esto parece mueble de exhibición' por celda de la rejilla."""
    acumulado = np.zeros((FILAS, COLUMNAS), dtype=np.float64)

    for frame in frames:
        gris = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        alto, ancho = gris.shape[:2]

        bordes_v = np.abs(cv2.Sobel(gris, cv2.CV_32F, 1, 0, ksize=3)) > 55
        bordes_h = np.abs(cv2.Sobel(gris, cv2.CV_32F, 0, 1, ksize=3)) > 55
        saturado = hsv[:, :, 1] > 85

        for f in range(FILAS):
            for c in range(COLUMNAS):
                y1, y2 = int(f * alto / FILAS), int((f + 1) * alto / FILAS)
                x1, x2 = int(c * ancho / COLUMNAS), int((c + 1) * ancho / COLUMNAS)

                dv = float(bordes_v[y1:y2, x1:x2].mean())
                dh = float(bordes_h[y1:y2, x1:x2].mean())
                ds = float(saturado[y1:y2, x1:x2].mean())

                # Los tres factores se combinan multiplicando la parte de
                # bordes: un muro liso saturado (una pared pintada) no debe
                # puntuar como estantería, y una reja sin producto tampoco.
                acumulado[f, c] += (0.5 * dv + 0.3 * dh) * (0.4 + 0.6 * ds)

    puntaje = acumulado / max(1, len(frames))
    maximo = puntaje.max()
    return puntaje / maximo if maximo > 0 else puntaje


def _puntaje_transito(tracking_path: Path | None, ancho: int, alto: int) -> np.ndarray:
    """Densidad de paso de personas por celda, normalizada a [0, 1]."""
    transito = np.zeros((FILAS, COLUMNAS), dtype=np.float64)
    if tracking_path is None or not Path(tracking_path).exists():
        return transito

    with Path(tracking_path).open("r", encoding="utf-8") as fh:
        for linea in fh:
            linea = linea.strip()
            if not linea:
                continue
            try:
                frame = json.loads(linea)
            except json.JSONDecodeError:
                continue

            for track in frame.get("tracks", []):
                bbox = track.get("bbox")
                if not bbox or len(bbox) != 4:
                    continue
                # Se usan los PIES, no el centroide: los pies marcan dónde
                # pisa la persona, que es lo que define el pasillo. El
                # centroide queda a la altura del torso y se solapa con el
                # estante que tiene detrás.
                cx = (bbox[0] + bbox[2]) / 2
                cy = bbox[3]
                c = int(cx * COLUMNAS / max(1, ancho))
                f = int(cy * FILAS / max(1, alto))
                if 0 <= f < FILAS and 0 <= c < COLUMNAS:
                    transito[f, c] += 1

    if transito.max() <= 0:
        return transito

    # Normalizar por el máximo sería un error: una persona que se queda quieta
    # en la caja acumula muchísimo más que un pasillo donde la gente se
    # reparte, así que el pasillo quedaría cerca de cero y no se detectaría.
    # Se normaliza por un percentil alto de las celdas CON tránsito y se
    # satura en 1, que mide "aquí pasa gente" en vez de "aquí pasa la mayor
    # cantidad de gente del video".
    con_paso = transito[transito > 0]
    referencia = float(np.percentile(con_paso, 75)) or float(transito.max())
    return np.clip(transito / referencia, 0.0, 1.0)


def _agrupar(mascara: np.ndarray) -> list[list[tuple[int, int]]]:
    """Componentes conexas de celdas (4-vecindad), sin dependencias extra."""
    visitado = np.zeros_like(mascara, dtype=bool)
    grupos: list[list[tuple[int, int]]] = []

    for f in range(FILAS):
        for c in range(COLUMNAS):
            if not mascara[f, c] or visitado[f, c]:
                continue
            pila = [(f, c)]
            visitado[f, c] = True
            grupo = []
            while pila:
                yf, yc = pila.pop()
                grupo.append((yf, yc))
                for df, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nf, nc = yf + df, yc + dc
                    if (
                        0 <= nf < FILAS
                        and 0 <= nc < COLUMNAS
                        and mascara[nf, nc]
                        and not visitado[nf, nc]
                    ):
                        visitado[nf, nc] = True
                        pila.append((nf, nc))
            grupos.append(grupo)

    return grupos


def _dividir_por_ancho(
    grupo: list[tuple[int, int]], max_ancho: int
) -> list[list[tuple[int, int]]]:
    """
    Corta un grupo de celdas en sub-grupos de a lo sumo `max_ancho` columnas
    contiguas, para no fusionar varias góndolas en fila en un único bloque.
    """
    columnas = sorted({c for _, c in grupo})
    if not columnas:
        return [grupo]

    corridas: list[list[int]] = []
    actual = [columnas[0]]
    for c in columnas[1:]:
        if c == actual[-1] + 1:
            actual.append(c)
        else:
            corridas.append(actual)
            actual = [c]
    corridas.append(actual)

    subgrupos: list[list[tuple[int, int]]] = []
    for corrida in corridas:
        for i in range(0, len(corrida), max_ancho):
            columnas_del_trozo = set(corrida[i : i + max_ancho])
            trozo = [(f, c) for f, c in grupo if c in columnas_del_trozo]
            if trozo:
                subgrupos.append(trozo)
    return subgrupos


def _celdas_a_poligono(
    grupo: list[tuple[int, int]], ancho: int, alto: int
) -> list[list[int]]:
    """Rectángulo envolvente del grupo de celdas, en píxeles."""
    fs = [f for f, _ in grupo]
    cs = [c for _, c in grupo]
    x1 = int(min(cs) * ancho / COLUMNAS)
    x2 = int((max(cs) + 1) * ancho / COLUMNAS) - 1
    y1 = int(min(fs) * alto / FILAS)
    y2 = int((max(fs) + 1) * alto / FILAS) - 1
    return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]


def transito_desde_detecciones(
    detecciones_por_frame: list[list[dict[str, Any]]],
    ancho: int,
    alto: int,
) -> np.ndarray:
    """
    Mapa de tránsito a partir de detecciones ya calculadas, sin tracking.jsonl.

    Existe porque la propuesta de zonas ocurre ANTES de procesar el video, y
    sin datos de tránsito no se pueden separar pasillos ni cajas: la caja de
    pago se define justamente como mueble CON gente parada encima. Sin esta
    señal, todo lo que tenga estructura se clasifica como góndola, que es lo
    que venía pasando (0 cajas detectadas en todas las corridas).

    Se alimenta de una pasada rápida del detector sobre frames muestreados: no
    hace falta identidad de personas para saber por dónde se camina, basta con
    dónde aparecen los pies.
    """
    transito = np.zeros((FILAS, COLUMNAS), dtype=np.float64)

    for detecciones in detecciones_por_frame:
        for det in detecciones:
            bbox = det.get("bbox")
            if not bbox or len(bbox) != 4:
                continue
            cx = (bbox[0] + bbox[2]) / 2
            cy = bbox[3]  # pies
            c = int(cx * COLUMNAS / max(1, ancho))
            f = int(cy * FILAS / max(1, alto))
            if 0 <= f < FILAS and 0 <= c < COLUMNAS:
                transito[f, c] += 1

    if transito.max() <= 0:
        return transito
    con_paso = transito[transito > 0]
    referencia = float(np.percentile(con_paso, 75)) or float(transito.max())
    return np.clip(transito / referencia, 0.0, 1.0)


def proponer_zonas(
    frames: list[np.ndarray],
    ancho: int,
    alto: int,
    tracking_path: Path | None = None,
    min_celdas: int = 2,
    transito_precalculado: np.ndarray | None = None,
) -> dict[str, Any]:
    """
    Propone un `zonas.json` para este video.

    Devuelve el dict listo para escribir, con un bloque `_propuesta` que
    documenta cómo se generó y con qué confianza. Ese bloque es importante:
    quien abra el archivo tiene que saber que no lo dibujó una persona.
    """
    if not frames:
        raise ValueError("No hay frames para analizar; no se pueden proponer zonas.")

    estructura = _puntaje_estructura(frames)
    transito = (
        transito_precalculado
        if transito_precalculado is not None
        else _puntaje_transito(tracking_path, ancho, alto)
    )
    hay_transito = bool(transito.max() > 0)

    # Umbrales relativos a la propia imagen: un video oscuro o de baja
    # resolución produce puntajes más bajos en conjunto, y un umbral fijo lo
    # dejaría sin ninguna zona.
    umbral_estructura = max(0.35, float(np.percentile(estructura, 60)))
    umbral_transito = 0.25

    es_estante = estructura >= umbral_estructura
    es_paso = transito >= umbral_transito

    mitad_inferior = np.zeros((FILAS, COLUMNAS), dtype=bool)
    mitad_inferior[int(FILAS * 0.55):, :] = True

    # Caja de pago: mueble con gente PARADA encima. Antes se exigía
    # `es_estante & es_paso`, y esas dos condiciones casi nunca coinciden en la
    # misma celda: donde hay mueble el detector de personas ve el torso, no los
    # pies, así que la celda del mueble queda sin tránsito y la caja NUNCA se
    # detectaba (0 cajas en todas las corridas reales).
    #
    # La señal correcta es la PERMANENCIA: en la caja la gente se queda quieta,
    # mientras que en un pasillo pasa de largo. Se mide como concentración de
    # tránsito: celdas donde se acumula mucho paso en poca área.
    if hay_transito:
        umbral_permanencia = max(0.6, float(np.percentile(transito[transito > 0], 90)))
        gente_detenida = transito >= umbral_permanencia
        # Vecindad de mueble: la celda de la caja o alguna contigua tiene
        # estructura. Se dilata la máscara de estante un paso.
        cerca_de_mueble = es_estante.copy()
        for eje in (0, 1):
            cerca_de_mueble |= np.roll(es_estante, 1, axis=eje)
            cerca_de_mueble |= np.roll(es_estante, -1, axis=eje)
        mascara_caja = gente_detenida & cerca_de_mueble & mitad_inferior
    else:
        mascara_caja = np.zeros_like(es_estante)
    mascara_gondola = es_estante & ~mascara_caja & (~es_paso if hay_transito else True)
    mascara_pasillo = es_paso & ~es_estante if hay_transito else np.zeros_like(es_estante)

    zonas: list[dict[str, Any]] = []
    contadores = {"gondola": 0, "pasillo": 0, "caja": 0}

    for tipo, mascara, prefijo in (
        ("gondola", mascara_gondola, "gondola_auto_"),
        ("caja", mascara_caja, "caja_"),
        ("pasillo", mascara_pasillo, "pasillo_"),
    ):
        grupos = _agrupar(mascara)
        if tipo == "gondola":
            grupos = [
                subgrupo
                for grupo in grupos
                for subgrupo in _dividir_por_ancho(grupo, MAX_ANCHO_GONDOLA_CELDAS)
            ]
        for grupo in grupos:
            if len(grupo) < min_celdas:
                continue
            confianza = float(np.mean([estructura[f, c] for f, c in grupo]))

            # Una caja sin estructura debajo no es una caja: es gente parada en
            # el piso (una fila, alguien esperando). Marcarla como caja haría
            # que se excluyera del análisis un área que sí es pasillo. Se
            # reclasifica en vez de descartarla, para no perder la información
            # de que ahí hay tránsito.
            if tipo == "caja" and confianza < 0.25:
                continue

            contadores[tipo] += 1
            zonas.append(
                {
                    "zone_id": f"{prefijo}{contadores[tipo]}",
                    "poligono": _celdas_a_poligono(grupo, ancho, alto),
                    "es_gondola": tipo == "gondola",
                    "_tipo_detectado": tipo,
                    "_confianza": round(confianza, 3),
                    "_celdas": len(grupo),
                }
            )

    return {
        "video_ref": "propuesta_automatica",
        "frame_width": ancho,
        "frame_height": alto,
        "zonas": zonas,
        "_propuesta": {
            "generada_por": "zonas_auto.proponer_zonas",
            "frames_analizados": len(frames),
            "uso_tracking": hay_transito,
            "umbral_estructura": round(umbral_estructura, 3),
            "conteo": contadores,
            "advertencia": (
                "Zonas PROPUESTAS automáticamente, no validadas por una persona. "
                "Revísalas con mapas_de_calor/src/zone_definer.py antes de "
                "presentar métricas: un layout mal definido produce cifras que "
                "parecen válidas y no lo son."
                + (
                    ""
                    if hay_transito
                    else " Además, no hubo datos de tránsito: sin saber por "
                    "dónde camina la gente no se pueden separar pasillos ni "
                    "cajas, así que esta propuesta es notablemente menos "
                    "confiable."
                )
            ),
        },
    }


def _a_tipos_python(obj):
    """
    Convierte tipos de NumPy a tipos nativos antes de serializar.

    numpy.bool_, numpy.float64 y numpy.int64 se comportan como sus
    equivalentes de Python pero el módulo json los rechaza. El error aparece
    recién al escribir el archivo, después de todo el análisis, así que
    conviene normalizar en un solo punto en vez de ir caso por caso.
    """
    if isinstance(obj, dict):
        return {k: _a_tipos_python(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_a_tipos_python(v) for v in obj]
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    return obj


def guardar_propuesta(propuesta: dict[str, Any], ruta: Path | str) -> Path:
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(
        json.dumps(_a_tipos_python(propuesta), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return ruta


def dibujar_propuesta(
    frame: np.ndarray, propuesta: dict[str, Any], ruta_salida: Path | str
) -> Path:
    """Guarda una imagen con las zonas propuestas, para revisarlas de un vistazo."""
    lienzo = frame.copy()
    colores = {
        "gondola": (140, 220, 140),
        "pasillo": (200, 200, 200),
        "caja": (90, 160, 255),
    }

    for zona in propuesta.get("zonas", []):
        pts = np.array(zona["poligono"], dtype=np.int32)
        color = colores.get(zona.get("_tipo_detectado", "gondola"), (200, 200, 200))
        cv2.polylines(lienzo, [pts], True, color, 2)
        cv2.putText(
            lienzo,
            f"{zona['zone_id']} ({zona.get('_confianza', 0):.2f})",
            (int(pts[0][0]) + 5, int(pts[0][1]) + 20),
            cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA,
        )

    ruta_salida = Path(ruta_salida)
    ruta_salida.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(ruta_salida), lienzo)
    return ruta_salida


def main() -> None:
    import argparse

    from preproceso import muestrear_frames

    parser = argparse.ArgumentParser(
        description="Propone zonas automáticamente a partir de un video"
    )
    parser.add_argument("--video", required=True)
    parser.add_argument("--tracking", default=None, help="tracking.jsonl del mismo video (recomendado)")
    parser.add_argument("--output", default="mapas_de_calor/config/zonas_propuestas.json")
    parser.add_argument("--preview", default=None, help="PNG con las zonas dibujadas")
    parser.add_argument("--frames", type=int, default=20)
    args = parser.parse_args()

    frames = muestrear_frames(args.video, n=args.frames)
    if not frames:
        raise SystemExit(f"No se pudo leer ningún frame de {args.video}")

    alto, ancho = frames[0].shape[:2]
    propuesta = proponer_zonas(
        frames, ancho, alto, Path(args.tracking) if args.tracking else None
    )
    ruta = guardar_propuesta(propuesta, args.output)

    conteo = propuesta["_propuesta"]["conteo"]
    print(f"[ok] Frames analizados: {len(frames)} ({ancho}x{alto})")
    print(f"[ok] Góndolas propuestas: {conteo['gondola']}")
    print(f"[ok] Pasillos propuestos: {conteo['pasillo']}")
    print(f"[ok] Cajas de pago propuestas: {conteo['caja']}")
    if not propuesta["_propuesta"]["uso_tracking"]:
        print("[aviso] Sin tracking.jsonl: propuesta menos confiable.")
    print(f"[ok] Propuesta: {ruta}")

    if args.preview:
        print(f"[ok] Vista previa: {dibujar_propuesta(frames[0], propuesta, args.preview)}")

    print("\n[!] REVISA las zonas antes de usarlas para métricas:")
    print("    python mapas_de_calor/src/zone_definer.py --video <video>")


if __name__ == "__main__":
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    main()
