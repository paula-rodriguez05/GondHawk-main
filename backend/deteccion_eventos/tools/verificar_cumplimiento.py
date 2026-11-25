"""
verificar_cumplimiento.py
Chequeo cruzado contra el validador del modulo 8 (Paula) — GondHawk.

En vez de confiar en que nuestra salida "deberia" pasar el validador de
cumplimiento, lo corremos de verdad sobre el archivo que generamos. Si el
modulo 8 cambia sus reglas, este script lo detecta antes de la demo y no
durante.

Nota tecnica: los archivos del modulo 8 vienen exportados de Google Colab y
pueden repetir `from __future__ import annotations` en medio del archivo, lo
que impide importarlos como modulo normal (en Colab cada celda se ejecuta por
separado, por eso alli si funciona). Este script los carga quitando esas
lineas repetidas cuando aparecen. No modifica el archivo original.

Uso:
    python deteccion_eventos/tools/verificar_cumplimiento.py \\
        --eventos deteccion_eventos/output/eventos_compliance.jsonl \\
        --validador validador_recomendador_v3.py
"""

from __future__ import annotations

import argparse
import json
import sys
import types
from pathlib import Path


def cargar_validador(ruta: Path):
    codigo = ruta.read_text(encoding="utf-8")

    # Se conserva el PRIMER "from __future__" (es valido y necesario) y se
    # quitan solo los repetidos mas abajo, que son los que rompen la
    # importacion. Antes se quitaban todos, asi que el aviso salia incluso
    # con archivos correctos.
    marca = "from __future__ import annotations\n"
    primero = codigo.find(marca)
    if primero == -1:
        limpio = codigo
    else:
        corte = primero + len(marca)
        limpio = codigo[:corte] + codigo[corte:].replace(marca, "")

    if limpio != codigo:
        print(
            "[aviso] Se quitaron imports '__future__' repetidos para poder cargar "
            f"{ruta.name} (pendiente de corregir en el modulo 8)."
        )
    modulo = types.ModuleType("validador_modulo8")
    # El archivo define dataclasses: Python las resuelve buscando su modulo en
    # sys.modules, asi que hay que registrarlo antes de ejecutarlo.
    sys.modules["validador_modulo8"] = modulo
    try:
        exec(compile(limpio, str(ruta), "exec"), modulo.__dict__)  # noqa: S102
    finally:
        sys.modules.pop("validador_modulo8", None)
    if not hasattr(modulo, "validar_registro"):
        raise SystemExit(f"{ruta} no expone validar_registro()")
    return modulo


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Corre el validador de cumplimiento del modulo 8 sobre nuestra salida"
    )
    parser.add_argument("--eventos", required=True, help="JSONL a validar")
    parser.add_argument(
        "--validador",
        default="validador_recomendador_v3.py",
        help="ruta al validador del modulo 8 (default: validador_recomendador_v3.py)",
    )
    args = parser.parse_args()

    validador = cargar_validador(Path(args.validador))

    total = 0
    cumplen = 0
    problemas: dict[str, int] = {}

    with Path(args.eventos).open("r", encoding="utf-8") as fh:
        for linea in fh:
            linea = linea.strip()
            if not linea:
                continue
            total += 1
            resultado = validador.validar_registro(json.loads(linea))
            if resultado["cumple"]:
                cumplen += 1
            for problema in resultado["problemas"]:
                problemas[problema] = problemas.get(problema, 0) + 1

    print(f"[ok] Registros evaluados: {total}")
    print(f"[ok] Conformes: {cumplen}/{total}")

    if problemas:
        print("[!] Problemas encontrados:")
        for problema, n in sorted(problemas.items(), key=lambda x: -x[1]):
            print(f"[!]   {n} x {problema}")
        raise SystemExit(1)

    print("[ok] La salida pasa el validador de privacidad por diseno del modulo 8.")


if __name__ == "__main__":
    main()
