# data/

Los videos NO se suben al repositorio (pesan mucho y no aportan al codigo).
Esta carpeta se deja vacia en git (ver `.gitkeep` a nivel de `output/`), y
cada quien descarga o coloca su propio video de prueba aqui.

## Opcion 1 — Video publico de ejemplo (recomendado para probar rapido)

```bash
python data/descargar_video_prueba.py
```

Esto descarga `vtest.avi`, un video academico de peatones caminando por una
via publica (usado en los ejemplos oficiales de OpenCV). Es libre de usar
para pruebas y no tiene restricciones de privacidad porque es material de
ejemplo publico, no una grabacion propia de la tienda.

## Opcion 2 — Video propio

Si el equipo graba su propio video en una tienda (con el consentimiento
correspondiente, segun la Ley 1581), colocalo aqui, por ejemplo:

```
data/tienda_prueba.mp4
```

Y luego corre el detector apuntando a esa ruta:

```bash
python src/run_detection.py --source data/tienda_prueba.mp4 --output output/detecciones.jsonl
```
