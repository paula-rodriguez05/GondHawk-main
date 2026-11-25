"""
heatmap_generator.py — A partir de trayectorias (reales de Juan o simuladas) y las zonas
definidas, genera:
  1. Un mapa de calor de flujo (output/heatmap.png + heatmap_matrix.npy suavizada
     + heatmap_raw.npy sin suavizar, util para umbrales exactos en el modulo 1).
  2. Conteos por zona (output/conteo_zonas.json): visitas unicas, frames ocupada, % tiempo.

Rendimiento: clasificacion punto->zona con mascaras rasterizadas (cv2.fillPoly +
lookup numpy), ~100x mas rapido que geometria en Python puro con video real.
point_in_polygon se conserva como referencia y para los tests.

No guarda ningun recorte de imagen de persona: solo trabaja con centroides numericos
(cumple privacidad por diseno, ver FORMATO_DATOS.md seccion 3).

Uso:
    python src/heatmap_generator.py \
        --trayectorias data/tracking_simulado.jsonl \
        --zonas config/zonas.json \
        --output-dir output \
        --frame-ref data/vtest.avi \
        --colormap turbo
"""
import argparse
import json
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from trajectory_reader import read_trajectories, load_zonas

COLORMAPS = {
    "jet": cv2.COLORMAP_JET,
    "turbo": cv2.COLORMAP_TURBO,
    "inferno": cv2.COLORMAP_INFERNO,
    "hot": cv2.COLORMAP_HOT,
    "magma": cv2.COLORMAP_MAGMA
}

def point_in_polygon(point, polygon) -> bool:
    """Ray casting simple. polygon: lista de [x, y].
    Se conserva como referencia/oracle para tests; el pipeline usa mascaras."""
    x, y = point
    n = len(polygon)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        intersect = ((yi > y) != (yj > y)) and (
            x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi
        )
        if intersect:
            inside = not inside
        j = i
    return inside


def build_zone_masks(zonas: list, width: int, height: int) -> dict:
    """Rasteriza cada zona una vez (cv2.fillPoly) y devuelve {zone_id: mask bool}.
    Clasificar un punto luego es un lookup O(1) por zona, sin geometria en Python."""
    masks = {}
    for zona in zonas:
        m = np.zeros((height, width), dtype=np.uint8)
        pts = np.array(zona["poligono"], dtype=np.int32)
        cv2.fillPoly(m, [pts], 1)
        masks[zona["zone_id"]] = m.astype(bool)
    return masks


def build_heatmap_and_counts(trayectorias_path: str, zonas_data: dict):
    width = zonas_data["frame_width"]
    height = zonas_data["frame_height"]
    zonas = zonas_data["zonas"]

    heatmap = np.zeros((height, width), dtype=np.float64)
    masks = build_zone_masks(zonas, width, height)

    visitas_por_zona = defaultdict(set)         # zone_id -> set(track_id)
    frames_ocupada_por_zona = defaultdict(set)  # zone_id -> set(frame_id) con >=1 persona
    frames_totales = set()

    for point in read_trajectories(trayectorias_path):
        frames_totales.add(point.frame_id)
        cx, cy = point.centroid
        cx_i, cy_i = int(round(cx)), int(round(cy))
        dentro = 0 <= cx_i < width and 0 <= cy_i < height
        if dentro:
            heatmap[cy_i, cx_i] += 1
            for zona in zonas:
                if masks[zona["zone_id"]][cy_i, cx_i]:
                    zid = zona["zone_id"]
                    visitas_por_zona[zid].add(point.track_id)
                    frames_ocupada_por_zona[zid].add(point.frame_id)

    n_frames = len(frames_totales) if frames_totales else 1

    conteos = []
    for zona in zonas:
        zid = zona["zone_id"]
        ocupada = len(frames_ocupada_por_zona.get(zid, set()))
        conteos.append({
            "zone_id": zid,
            "visitas_unicas": len(visitas_por_zona.get(zid, set())),
            "frames_ocupada": ocupada,
            # denominador: frames con >=1 track en el video (frames con datos),
            # NO el total de frames del archivo. Documentado en FORMATO_DATOS.md 2.2.
            "pct_tiempo_ocupada": round(100 * ocupada / n_frames, 2),
        })

    resultado_conteos = {
        "video_ref": zonas_data.get("video_ref"),
        "frames_procesados": n_frames,
        "zonas": conteos,
    }
    return heatmap, resultado_conteos


def smooth_heatmap(heatmap: np.ndarray, ksize: int = 25) -> np.ndarray:
    if ksize % 2 == 0:
        ksize += 1
    return cv2.GaussianBlur(heatmap, (ksize, ksize), 0)


def normalize_heatmap(heatmap: np.ndarray, clip_percentile: float = 95.0,
                      log_scale: bool = True) -> np.ndarray:
    """Normaliza a 0-1 para visualizacion.
    - log1p comprime los valores extremos (un punto muy caliente no aplasta el resto).
    - clip al percentil indicado sobre los valores > 0: el maximo absoluto deja de
      dominar la escala y el mapa completo se vuelve legible.
    """
    vals = heatmap[heatmap > 0]
    if vals.size == 0:
        return np.zeros_like(heatmap)
    data = np.log1p(heatmap) if log_scale else heatmap.copy()
    if log_scale:
        vals = np.log1p(vals)
    thresh = np.percentile(vals, clip_percentile)
    if thresh <= 0:
        max_val = data.max()
        return data / max_val if max_val > 0 else data
    return np.clip(data / thresh, 0.0, 1.0)


def render_heatmap_image(heatmap: np.ndarray, frame_ref: np.ndarray = None,
                         clip_percentile: float = 95.0, log_scale: bool = True,
                         colormap_name: str = "turbo", zonas: list = None) -> np.ndarray:
    norm = normalize_heatmap(heatmap, clip_percentile, log_scale)
    norm_u8 = (norm * 255).astype(np.uint8)
    
    cmap = COLORMAPS.get(colormap_name.lower(), cv2.COLORMAP_TURBO)
    colored = cv2.applyColorMap(norm_u8, cmap)

    if frame_ref is not None:
        base = cv2.resize(frame_ref, (heatmap.shape[1], heatmap.shape[0]))
        
        # Enmascarar exterior: oscurecer el fondo fuera de las zonas definidas
        if zonas:
            mask = np.zeros(base.shape[:2], dtype=np.uint8)
            for zona in zonas:
                pts = np.array(zona["poligono"], dtype=np.int32)
                cv2.fillPoly(mask, [pts], 1)
            # Aplicar atenuación al 30% fuera de la máscara
            base[mask == 0] = (base[mask == 0] * 0.3).astype(np.uint8)

        overlay = cv2.addWeighted(base, 0.55, colored, 0.45, 0)
        return overlay
    return colored


def draw_zonas_on_image(img: np.ndarray, zonas: list, conteos: list) -> np.ndarray:
    out = img.copy()
    conteos_dict = {c["zone_id"]: c for c in conteos}
    font = cv2.FONT_HERSHEY_SIMPLEX
    
    for zona in zonas:
        pts = np.array(zona["poligono"], dtype=np.int32)
        zid = zona["zone_id"]
        stats = conteos_dict.get(zid, {})
        pct = stats.get("pct_tiempo_ocupada", 0)
        
        # Color dinámico: Rojo para caliente (>50%), Blanco para normal/fría
        if pct > 50:
            color_border = (0, 0, 255)      # BGR: Rojo
            color_text2 = (0, 200, 255)     # BGR: Amarillo dorado
        else:
            color_border = (255, 255, 255)  # BGR: Blanco
            color_text2 = (255, 255, 255)
            
        # Dibujar polígono más grueso
        cv2.polylines(out, [pts], isClosed=True, color=color_border, thickness=3)
        
        label1 = f"{zid}"
        label2 = f"{pct}% ocupada"
        
        (w1, h1), _ = cv2.getTextSize(label1, font, 0.5, 1)
        (w2, h2), _ = cv2.getTextSize(label2, font, 0.5, 1)
        w = max(w1, w2)
        h = h1 + h2 + 8
        
        x, y = pts[0]
        # Prevención de desborde superior
        if y - h - 10 < 0:
            y = y + h + 20
            
        # Fondo oscuro para legibilidad
        cv2.rectangle(out, (x-2, y-h-4), (x+w+4, y+4), (0,0,0), -1)
        # Textos
        cv2.putText(out, label1, (x, y-h2-4), font, 0.5, (255, 255, 255), 1)
        cv2.putText(out, label2, (x, y), font, 0.5, color_text2, 1)
        
    return out


def save_with_colorbar(img_bgr: np.ndarray, out_path: str, colormap_name: str):
    """Render final image with colorbar and titles using matplotlib."""
    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    
    fig, ax = plt.subplots(figsize=(12, 8))
    ax.imshow(img_rgb)
    ax.axis('off')
    
    # Mapear el nombre a matplotlib
    cmap_plt = colormap_name.lower() if colormap_name.lower() in plt.colormaps() else 'turbo'
    
    sm = plt.cm.ScalarMappable(cmap=cmap_plt, norm=plt.Normalize(vmin=0, vmax=1))
    cbar = fig.colorbar(sm, ax=ax, fraction=0.046, pad=0.04)
    cbar.set_label('Densidad Relativa de Flujo', rotation=270, labelpad=20, fontsize=12, color='white')
    cbar.ax.yaxis.set_tick_params(color='white', labelcolor='white')
    
    plt.title("Análisis de Flujo y Zonas Calientes", pad=20, fontsize=16, fontweight='bold', color='white')
    plt.tight_layout()
    
    # Fondo oscuro tipo dashboard para el borde
    fig.patch.set_facecolor('#0f172a')
    plt.savefig(out_path, dpi=150, bbox_inches='tight', facecolor=fig.get_facecolor(), edgecolor='none')
    plt.close(fig)


def load_reference_frame(video_path: str):
    if not video_path:
        return None
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"Aviso: no se pudo abrir {video_path}, se genera heatmap sin frame de fondo.")
        return None
    ok, frame = cap.read()
    cap.release()
    return frame if ok else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trayectorias", required=True,
                        help="JSONL de tracking (real de Juan o simulado)")
    parser.add_argument("--zonas", default="config/zonas.json")
    parser.add_argument("--output-dir", default="output")
    parser.add_argument("--frame-ref", default=None, help="Video para tomar un frame de fondo")
    parser.add_argument("--blur", type=int, default=25, help="Kernel de suavizado del heatmap")
    parser.add_argument("--clip-percentile", type=float, default=95.0,
                        help="Percentil de corte para la normalizacion visual (95 = legible)")
    parser.add_argument("--linear-scale", action="store_true",
                        help="Desactivar la escala logaritmica (no recomendado)")
    parser.add_argument("--colormap", default="turbo",
                        choices=["jet", "turbo", "inferno", "hot", "magma"],
                        help="Colormap a utilizar (default: turbo)")
    args = parser.parse_args()

    zonas_data = load_zonas(args.zonas)
    zonas_list = zonas_data["zonas"]
    heatmap, conteos = build_heatmap_and_counts(args.trayectorias, zonas_data)
    heatmap_smooth = smooth_heatmap(heatmap, args.blur)

    frame_ref = load_reference_frame(args.frame_ref)
    
    # 1. Renderizar heatmap (aplicando colormap y overlay sobre el video enmascarado)
    img = render_heatmap_image(heatmap_smooth, frame_ref,
                               clip_percentile=args.clip_percentile,
                               log_scale=not args.linear_scale,
                               colormap_name=args.colormap,
                               zonas=zonas_list)
    
    # 2. Dibujar polígonos y etiquetas con fondo
    img = draw_zonas_on_image(img, zonas_list, conteos["zonas"])

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    heatmap_path = str(out_dir / "heatmap.png")
    
    # 3. Guardar imagen final usando Matplotlib (colorbar + título)
    save_with_colorbar(img, heatmap_path, args.colormap)

    np.save(str(out_dir / "heatmap_matrix.npy"), heatmap_smooth)  # suavizada (dashboard)
    np.save(str(out_dir / "heatmap_raw.npy"), heatmap)            # cruda (modulo 1: umbrales exactos)
    with open(out_dir / "conteo_zonas.json", "w", encoding="utf-8") as f:
        json.dump(conteos, f, indent=2, ensure_ascii=False)

    print(f"Heatmap guardado en {heatmap_path}")
    print(f"Matrices guardadas: heatmap_matrix.npy (suavizada) + heatmap_raw.npy (cruda)")
    print(f"Conteos por zona guardados en {out_dir / 'conteo_zonas.json'}")
    for z in conteos["zonas"]:
        print(f"  {z['zone_id']}: {z['visitas_unicas']} visitas, "
              f"{z['pct_tiempo_ocupada']}% del tiempo ocupada")


if __name__ == "__main__":
    main()
