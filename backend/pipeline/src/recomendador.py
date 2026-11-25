"""
recomendador.py
Motor de recomendaciones de space management — GondHawk.

Reemplaza las alertas fijas (`_generar_alertas`) por recomendaciones
personalizadas al análisis: qué producto mover, a dónde y por qué, en el
lenguaje de un jefe de categoría y no en el de un pipeline de visión.

Funciona en dos capas, y el orden importa:

1. CAPA DE DIAGNÓSTICO (determinista, siempre corre)
   Clasifica cada góndola en un patrón conocido de retail a partir de sus
   propias cifras: tráfico alto sin parada, alta toma con alto rechazo, zona
   muerta, punto caliente. Esta capa produce el dato duro — qué pasa, con qué
   números y con qué prioridad — y no depende de ningún modelo externo.

2. CAPA DE REDACCIÓN (LLM, opcional)
   Toma ese diagnóstico y lo convierte en una recomendación concreta,
   comparando zonas entre sí ("mueve el SKU de B1, que tiene 3 veces el
   tráfico de A2, al espacio de A2"). Si no hay API key o la llamada falla,
   se usa la redacción de plantilla y el sistema sigue funcionando.

Esta separación es deliberada y hay que poder defenderla: las CIFRAS nunca las
inventa un modelo de lenguaje. El LLM redacta y prioriza sobre datos ya
calculados; no estima tasas, no completa números faltantes y no decide si una
zona es fría. Un LLM que inventa un porcentaje en un reporte de retail es peor
que no tener recomendaciones.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

MODELO_POR_DEFECTO = "claude-sonnet-4-6"
TIMEOUT_S = 30

# Umbrales de diagnóstico. Están aquí arriba, con nombre, porque son
# decisiones de negocio que el equipo debe poder discutir y ajustar, no
# constantes escondidas dentro de una función.
UMBRAL_TRAFICO_RELEVANTE = 5      # menos visitas que esto: muestra insuficiente
UMBRAL_PARADA_BAJA = 0.20         # se detiene < 20% de quienes pasan
UMBRAL_INTERACCION_BAJA = 0.15
UMBRAL_INTERACCION_ALTA = 0.50
UMBRAL_RECHAZO_ALTO = 0.40


def _clasificar(zona: dict[str, Any]) -> dict[str, Any] | None:
    """Asigna a una zona su patrón de retail, con prioridad y evidencia."""
    embudo = zona.get("embudo", {})
    visitas = embudo.get("visitas", 0)
    paradas = embudo.get("se_detiene", 0)
    tomas = embudo.get("toma_producto", 0)
    devoluciones = embudo.get("devuelve", 0)

    if visitas < UMBRAL_TRAFICO_RELEVANTE:
        # Con muy poco tráfico cualquier tasa es ruido estadístico. Decirlo es
        # más útil que emitir una recomendación sobre 3 visitas.
        return {
            "zone_id": zona.get("zone_id"),
            "patron": "muestra_insuficiente",
            "titulo": "Datos insuficientes",
            "prioridad": "informativa",
            "evidencia": {"visitas": visitas},
            "detalle": (
                f"Solo {visitas} visitas registradas: no alcanza para sacar "
                "conclusiones sobre esta zona."
            ),
            "accion": "Ampliar la ventana de grabación antes de decidir sobre esta góndola.",
        }

    # Las tasas se RECALCULAN del embudo en vez de leerse del JSON. Si el
    # campo falta o llega con otro nombre, leerlo devolvería 0.0 y el
    # diagnóstico reportaría "0% se detiene" sobre zonas que sí tienen
    # paradas: un cero silencioso es el peor error posible en un reporte,
    # porque parece un hallazgo.
    tasa_parada = paradas / visitas if visitas else 0.0
    tasa_interaccion = tomas / paradas if paradas else 0.0
    tasa_rechazo = devoluciones / tomas if tomas else 0.0

    if tomas >= 2 and tasa_rechazo >= UMBRAL_RECHAZO_ALTO:
        return {
            "zone_id": zona.get("zone_id"),
            "patron": "rechazo_alto",
            "titulo": "El producto se toma pero se devuelve",
            "prioridad": "alta",
            "evidencia": {"tomas": tomas, "devoluciones": devoluciones, "tasa_rechazo": tasa_rechazo},
            "detalle": (
                f"De {tomas} productos tomados, {devoluciones} vuelven al estante "
                f"({tasa_rechazo * 100:.0f}%). El producto atrae, pero algo lo frena "
                "en la mano del comprador."
            ),
            "accion": (
                "Revisar precio visible, información de empaque y fecha de vencimiento. "
                "Es el patrón típico de sorpresa de precio en el punto de decisión."
            ),
        }

    if tasa_interaccion >= UMBRAL_INTERACCION_ALTA and paradas >= 3:
        return {
            "zone_id": zona.get("zone_id"),
            "patron": "punto_caliente",
            "titulo": "Zona de alto rendimiento",
            "prioridad": "oportunidad",
            "evidencia": {"paradas": paradas, "tomas": tomas, "tasa_interaccion": tasa_interaccion},
            "detalle": (
                f"{tasa_interaccion * 100:.0f}% de quienes se detienen toman producto. "
                "Es el espacio más productivo del layout medido."
            ),
            "accion": (
                "Proteger este facing y considerarlo para lanzamientos o productos "
                "de mayor margen."
            ),
        }

    if tasa_parada <= UMBRAL_PARADA_BAJA and visitas >= 10:
        return {
            "zone_id": zona.get("zone_id"),
            "patron": "trafico_sin_parada",
            "titulo": "Pasa mucha gente, casi nadie se detiene",
            "prioridad": "alta",
            "evidencia": {"visitas": visitas, "paradas": paradas, "tasa_detencion": tasa_parada},
            "detalle": (
                f"{visitas} personas pasan y solo {paradas} se detienen "
                f"({tasa_parada * 100:.0f}%). El tráfico está, la atención no."
            ),
            "accion": (
                "Es una góndola de paso, no de compra. Señalización a la altura de "
                "los ojos o un quiebre visual en el lineal para romper la marcha."
            ),
        }

    if tasa_interaccion < UMBRAL_INTERACCION_BAJA and paradas >= 3:
        return {
            "zone_id": zona.get("zone_id"),
            "patron": "mira_no_toca",
            "titulo": "Se detienen pero no toman el producto",
            "prioridad": "media",
            "evidencia": {"paradas": paradas, "tomas": tomas, "tasa_interaccion": tasa_interaccion},
            "detalle": (
                f"{paradas} personas se detuvieron y solo {tomas} tomaron producto. "
                "Hay interés, pero no se convierte en contacto físico."
            ),
            "accion": (
                "Revisar accesibilidad del facing (altura, profundidad) y claridad de "
                "precio. El comprador mira, evalúa y descarta sin tocar."
            ),
        }

    return None


def _comparar_zonas(diagnosticos: list[dict[str, Any]], zonas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Recomendación de reubicación cruzando dos zonas.

    Es la recomendación que el reto pide como deseable: no basta con decir que
    una zona va mal, hay que decir qué hacer con el espacio. Se busca el par
    (zona con tráfico alto y baja conversión) + (zona con alta conversión y
    poco tráfico): mover el producto de la segunda al espacio de la primera
    aprovecha el flujo que ya existe.
    """
    por_id = {z.get("zone_id"): z for z in zonas}

    con_trafico_desperdiciado = [
        d for d in diagnosticos
        if d["patron"] in ("trafico_sin_parada", "mira_no_toca")
    ]
    productivas = [d for d in diagnosticos if d["patron"] == "punto_caliente"]

    extras = []
    for productiva in productivas:
        zona_p = por_id.get(productiva["zone_id"], {})
        visitas_p = zona_p.get("embudo", {}).get("visitas", 0)

        for desperdiciada in con_trafico_desperdiciado:
            zona_d = por_id.get(desperdiciada["zone_id"], {})
            visitas_d = zona_d.get("embudo", {}).get("visitas", 0)

            if visitas_d > visitas_p * 1.5:
                extras.append({
                    "zone_id": f"{productiva['zone_id']} → {desperdiciada['zone_id']}",
                    "patron": "reubicacion",
                    "titulo": "Oportunidad de reubicación",
                    "prioridad": "alta",
                    "evidencia": {
                        "visitas_origen": visitas_p,
                        "visitas_destino": visitas_d,
                        "multiplicador_trafico": round(visitas_d / max(1, visitas_p), 1),
                    },
                    "detalle": (
                        f"{desperdiciada['zone_id']} recibe {visitas_d} visitas frente a "
                        f"{visitas_p} de {productiva['zone_id']}, pero convierte mucho peor. "
                        f"El producto que funciona en {productiva['zone_id']} está en el "
                        "espacio con menos flujo."
                    ),
                    "accion": (
                        f"Evaluar mover el producto de {productiva['zone_id']} al espacio de "
                        f"{desperdiciada['zone_id']} para exponerlo a "
                        f"{round(visitas_d / max(1, visitas_p), 1)}x el tráfico actual."
                    ),
                })
    return extras


def diagnosticar(metricas: dict[str, Any]) -> list[dict[str, Any]]:
    """Capa 1: diagnóstico determinista. Nunca falla ni depende de red."""
    zonas = [z for z in metricas.get("zonas", []) if z.get("zone_id")]
    diagnosticos = [d for d in (_clasificar(z) for z in zonas) if d]
    diagnosticos.extend(_comparar_zonas(diagnosticos, zonas))

    orden = {"alta": 0, "oportunidad": 1, "media": 2, "informativa": 3}
    diagnosticos.sort(key=lambda d: orden.get(d.get("prioridad"), 9))
    return diagnosticos


# ── Capa 2: redacción con LLM ───────────────────────────────────────────────

PROMPT_SISTEMA = """Eres un analista de space management en retail. Recibes el diagnóstico \
YA CALCULADO de un análisis de video de góndolas y lo conviertes en recomendaciones \
accionables para un jefe de categoría.

REGLAS ESTRICTAS:
- NO inventes ni estimes cifras. Usa solo los números que aparecen en el diagnóstico.
- Si un dato no está, no lo menciones. Nunca completes con supuestos.
- Habla de producto, espacio y comprador; no de píxeles, tracking ni modelos.
- Cada recomendación debe decir qué hacer, no solo qué pasa.
- Máximo 2 frases por campo. Español de Colombia, directo, sin adjetivos de marketing.

Devuelve SOLO un JSON con esta forma, sin markdown ni texto adicional:
{"recomendaciones": [{"zone_id": "...", "titulo": "...", "detalle": "...", \
"accion": "...", "prioridad": "alta|media|oportunidad|informativa"}]}"""


def _llamar_llm(diagnosticos: list[dict[str, Any]], total: dict[str, Any],
                api_key: str, modelo: str) -> list[dict[str, Any]] | None:
    payload = json.dumps({
        "model": modelo,
        "max_tokens": 2000,
        "system": PROMPT_SISTEMA,
        "messages": [{
            "role": "user",
            "content": json.dumps(
                {"embudo_global": total, "diagnostico_por_zona": diagnosticos},
                ensure_ascii=False,
            ),
        }],
    }).encode("utf-8")

    peticion = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "content-type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
    )

    with urllib.request.urlopen(peticion, timeout=TIMEOUT_S) as respuesta:
        cuerpo = json.loads(respuesta.read().decode("utf-8"))

    texto = "".join(
        bloque.get("text", "") for bloque in cuerpo.get("content", [])
        if bloque.get("type") == "text"
    ).strip()

    # El modelo a veces envuelve el JSON en un bloque de código pese a la
    # instrucción; se limpia antes de parsear.
    if texto.startswith("```"):
        texto = texto.split("```")[1]
        if texto.startswith("json"):
            texto = texto[4:]

    datos = json.loads(texto)
    return datos.get("recomendaciones")


def _validar_redaccion(
    redactadas: list[dict[str, Any]], diagnosticos: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """
    Descarta recomendaciones del LLM que hablen de zonas inexistentes.

    Es la única defensa real contra que el modelo invente una góndola. No se
    valida el contenido del texto — eso no se puede automatizar — pero sí que
    cada recomendación corresponda a una zona que existe en el diagnóstico.
    """
    validas = {d["zone_id"] for d in diagnosticos}
    return [r for r in redactadas if r.get("zone_id") in validas]


def generar_recomendaciones(
    metricas: dict[str, Any],
    usar_ia: bool = True,
    api_key: str | None = None,
    modelo: str = MODELO_POR_DEFECTO,
) -> dict[str, Any]:
    """
    Devuelve las recomendaciones y de dónde salieron.

    El campo `fuente` es importante para la trazabilidad: quien lea el reporte
    tiene que saber si el texto lo redactó un modelo o si viene de plantilla.
    """
    diagnosticos = diagnosticar(metricas)
    if not diagnosticos:
        return {"recomendaciones": [], "fuente": "sin_hallazgos", "diagnostico": []}

    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")

    if usar_ia and api_key:
        try:
            redactadas = _llamar_llm(diagnosticos, metricas.get("total", {}), api_key, modelo)
            if redactadas:
                redactadas = _validar_redaccion(redactadas, diagnosticos)
            if redactadas:
                return {
                    "recomendaciones": redactadas,
                    "fuente": f"ia:{modelo}",
                    "diagnostico": diagnosticos,
                }
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
            print(f"[aviso] No se pudo consultar el modelo ({exc}); se usa la redacción base.")
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            print(f"[aviso] Respuesta del modelo no utilizable ({exc}); se usa la redacción base.")

    return {
        "recomendaciones": diagnosticos,
        "fuente": "reglas" if not api_key else "reglas_por_fallo_ia",
        "diagnostico": diagnosticos,
    }


def main() -> None:
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Genera recomendaciones de space management")
    parser.add_argument("--metricas", default="pipeline/output/metricas_interaccion.json")
    parser.add_argument("--sin-ia", action="store_true", help="Solo reglas, sin llamar al modelo")
    parser.add_argument("--modelo", default=MODELO_POR_DEFECTO)
    parser.add_argument("--guardar", action="store_true",
                        help="Escribe las recomendaciones dentro del archivo de métricas")
    args = parser.parse_args()

    ruta = Path(args.metricas)
    metricas = json.loads(ruta.read_text(encoding="utf-8"))
    resultado = generar_recomendaciones(metricas, usar_ia=not args.sin_ia, modelo=args.modelo)

    print(f"[ok] Fuente: {resultado['fuente']}")
    print(f"[ok] Recomendaciones: {len(resultado['recomendaciones'])}\n")
    for r in resultado["recomendaciones"]:
        print(f"  [{r.get('prioridad', '—').upper()}] {r.get('zone_id')} — {r.get('titulo')}")
        print(f"      {r.get('detalle', '')}")
        if r.get("accion"):
            print(f"      → {r['accion']}")
        print()

    if args.guardar:
        metricas["recomendaciones"] = resultado["recomendaciones"]
        metricas["recomendaciones_fuente"] = resultado["fuente"]
        ruta.write_text(json.dumps(metricas, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[ok] Guardadas en {ruta}")


if __name__ == "__main__":
    main()
