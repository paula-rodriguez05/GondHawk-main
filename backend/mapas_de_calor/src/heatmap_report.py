"""
heatmap_report.py - Genera un poster analítico (Grid) a partir de los resultados
del heatmap generados por heatmap_generator.py.

Combina una vista global y recortes individuales de cada zona, con una tabla
de métricas.

Uso:
    python src/heatmap_report.py --output output/poster.png
"""
import argparse
import json
import sys
import cv2
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from backend.mapas_de_calor.src.heatmap_generator import normalize_heatmap

def main():
    parser = argparse.ArgumentParser(description="Generar Poster Analítico")
    parser.add_argument("--matrix", default="output/heatmap_matrix.npy")
    parser.add_argument("--conteos", default="output/conteo_zonas.json")
    parser.add_argument("--zonas", default="config/zonas.json")
    parser.add_argument("--frame-ref", default="data/vtest.avi")
    parser.add_argument("--output", default="output/poster.png")
    parser.add_argument("--colormap", default="turbo")
    args = parser.parse_args()

    # Cargar datos
    if not Path(args.matrix).exists():
        print(f"Error: No se encontró {args.matrix}.")
        return
    
    heatmap_matrix = np.load(args.matrix)
    
    with open(args.conteos, "r", encoding="utf-8") as f:
        conteos = json.load(f)["zonas"]
    conteos_dict = {c["zone_id"]: c for c in conteos}
    
    with open(args.zonas, "r", encoding="utf-8") as f:
        zonas = json.load(f)["zonas"]

    # Preparar imagen base (Video)
    cap = cv2.VideoCapture(args.frame_ref)
    ok, frame = False, None
    if cap.isOpened():
        ok, frame = cap.read()
    cap.release()
    
    h, w = heatmap_matrix.shape
    if ok and frame is not None:
        frame = cv2.resize(frame, (w, h))
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    else:
        frame = np.zeros((h, w, 3), dtype=np.uint8)

    # Preparar overlay del heatmap completo
    norm = normalize_heatmap(heatmap_matrix)
    
    import matplotlib as mpl
    cmap = mpl.colormaps.get_cmap(args.colormap if args.colormap in plt.colormaps() else 'turbo')
    # Aplicar colormap manual para rgb
    colored_rgb = (cmap(norm)[:, :, :3] * 255).astype(np.uint8)
    
    # Overlay global
    mask_global = np.zeros((h, w), dtype=np.uint8)
    for zona in zonas:
        pts = np.array(zona["poligono"], dtype=np.int32)
        cv2.fillPoly(mask_global, [pts], 1)
        
    base_global = frame.copy()
    base_global[mask_global == 0] = (base_global[mask_global == 0] * 0.3).astype(np.uint8)
    img_global = cv2.addWeighted(base_global, 0.55, colored_rgb, 0.45, 0)
    
    # Configurar Gráfico Matplotlib
    fig = plt.figure(figsize=(16, 12), facecolor='#0f172a')
    
    n_zonas = len(zonas)
    # Ancho de cada panel proporcional al ancho del poligono de la zona,
    # asi el pasillo (zona ancha) no queda comprimido (punto 3 de la revision).
    width_ratios = []
    for zona in zonas:
        pts = np.array(zona["poligono"], dtype=np.int32)
        ancho = max(10, pts[:, 0].max() - pts[:, 0].min())
        width_ratios.append(ancho)
    gs = gridspec.GridSpec(3, n_zonas, figure=fig, hspace=0.4, wspace=0.3,
                           width_ratios=width_ratios)
    
    # Imagen Principal
    ax_main = fig.add_subplot(gs[0:2, :])
    ax_main.imshow(img_global)
    ax_main.axis('off')
    ax_main.set_title("Análisis de Flujo Global - GondHawk", color='white', fontsize=24, pad=15)
    
    # Dibujar polígonos en el main para contexto
    for zona in zonas:
        pts = np.array(zona["poligono"], dtype=np.int32)
        # Cerrar el polígono para matplotlib
        pts = np.vstack((pts, pts[0]))
        ax_main.plot(pts[:,0], pts[:,1], color='white', linewidth=2, alpha=0.5)

    # Subgráficos por zona
    for idx, zona in enumerate(zonas):
        ax_zone = fig.add_subplot(gs[2, idx])
        zid = zona["zone_id"]
        stats = conteos_dict.get(zid, {})
        pct = stats.get("pct_tiempo_ocupada", 0)
        visitas = stats.get("visitas_unicas", 0)
        
        # Calcular bounding box de la zona
        pts = np.array(zona["poligono"], dtype=np.int32)
        x_min, y_min = pts.min(axis=0)
        x_max, y_max = pts.max(axis=0)
        
        # Margen de 20px
        pad = 20
        y1, y2 = max(0, y_min-pad), min(h, y_max+pad)
        x1, x2 = max(0, x_min-pad), min(w, x_max+pad)
        
        # Crop de img_global
        crop = img_global[y1:y2, x1:x2]
        
        ax_zone.imshow(crop)
        ax_zone.axis('off')
        
        # Estado (Caliente / Frío). Sin emojis: matplotlib no los renderiza (punto 1).
        estado = "CALIENTE ▲" if pct > 50 else "FRÍA ▼"
        color_title = "#ef4444" if pct > 50 else "#60a5fa"

        ax_zone.set_title(f"{zid}\n{estado} {pct}% | {visitas} visitas", 
                          color=color_title, fontsize=12, pad=10, fontweight='bold')
        
    plt.savefig(args.output, dpi=200, bbox_inches='tight', facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"Poster analítico guardado en {args.output}")

if __name__ == "__main__":
    main()
