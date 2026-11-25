"""
zone_definer.py — Herramienta interactiva para dibujar los polígonos de las zonas
(góndolas, pasillos) sobre un frame real del video y guardarlos en config/zonas.json.

Uso:
    python src/zone_definer.py --video data/vtest.avi --frame 0 --output config/zonas.json

Controles:
    - Click izquierdo: agrega un punto al polígono actual.
    - 'n': cierra el polígono actual y pide el zone_id para guardarlo.
    - 'z': deshace el último punto agregado.
    - 'c': cancela el polígono actual sin guardar.
    - 's': guarda todas las zonas definidas hasta el momento en el JSON de salida.
    - 'q': sale sin guardar cambios pendientes (ya guardado con 's' se conserva).

Los zone_id deben coincidir con el catálogo acordado con Paula (módulo 8):
gondola_A1, gondola_A2, gondola_A3, pasillo_central, gondola_B1.
"""
import argparse
import json
import os
from pathlib import Path

import cv2

WINDOW_NAME = "Definir zonas - Ship Club (Arturo, modulo 4)"


class ZoneDefiner:
    def __init__(self, frame, frame_width, frame_height, video_ref):
        self.base_frame = frame
        self.frame_width = frame_width
        self.frame_height = frame_height
        self.video_ref = video_ref
        self.zonas = []  # lista de {"zone_id": str, "poligono": [[x,y], ...]}
        self.current_points = []

    def mouse_callback(self, event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            self.current_points.append([x, y])

    def render(self):
        img = self.base_frame.copy()

        # zonas ya guardadas
        for zona in self.zonas:
            pts = zona["poligono"]
            for i in range(len(pts)):
                p1 = tuple(pts[i])
                p2 = tuple(pts[(i + 1) % len(pts)])
                cv2.line(img, p1, p2, (0, 200, 0), 2)
            if pts:
                cv2.putText(img, zona["zone_id"], tuple(pts[0]),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 200, 0), 2)

        # polígono en progreso
        for i, p in enumerate(self.current_points):
            cv2.circle(img, tuple(p), 4, (0, 0, 255), -1)
            if i > 0:
                cv2.line(img, tuple(self.current_points[i - 1]), tuple(p), (0, 0, 255), 2)

        cv2.putText(img, "n=cerrar poligono | z=deshacer | c=cancelar | s=guardar | q=salir",
                    (10, self.frame_height - 15), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        return img

    def close_polygon(self):
        if len(self.current_points) < 3:
            print("Necesitas al menos 3 puntos para cerrar un poligono.")
            return
        zone_id = input("zone_id para esta zona (ej: gondola_A1): ").strip()
        if not zone_id:
            print("zone_id vacio, poligono descartado.")
            self.current_points = []
            return
        self.zonas.append({"zone_id": zone_id, "poligono": self.current_points})
        print(f"Zona '{zone_id}' agregada con {len(self.current_points)} puntos.")
        self.current_points = []

    def save(self, output_path):
        data = {
            "video_ref": self.video_ref,
            "frame_width": self.frame_width,
            "frame_height": self.frame_height,
            "zonas": self.zonas,
        }
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"Guardado en {output_path} ({len(self.zonas)} zonas).")


def load_frame(video_path, frame_index):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise FileNotFoundError(f"No se pudo abrir el video: {video_path}")
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise RuntimeError(f"No se pudo leer el frame {frame_index} de {video_path}")
    return frame


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", required=True, help="Ruta al video (ej: data/vtest.avi)")
    parser.add_argument("--frame", type=int, default=0, help="Indice de frame de referencia")
    parser.add_argument("--output", default="config/zonas.json", help="JSON de salida")
    args = parser.parse_args()

    frame = load_frame(args.video, args.frame)
    h, w = frame.shape[:2]
    definer = ZoneDefiner(frame, w, h, os.path.basename(args.video))

    cv2.namedWindow(WINDOW_NAME)
    cv2.setMouseCallback(WINDOW_NAME, definer.mouse_callback)

    print("Herramienta de definicion de zonas. Ve la ventana de video para dibujar.")
    while True:
        cv2.imshow(WINDOW_NAME, definer.render())
        key = cv2.waitKey(20) & 0xFF
        if key == ord("n"):
            definer.close_polygon()
        elif key == ord("z") and definer.current_points:
            definer.current_points.pop()
        elif key == ord("c"):
            definer.current_points = []
        elif key == ord("s"):
            definer.save(args.output)
        elif key == ord("q"):
            break

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
