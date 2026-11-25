# GondHawk: ejecución y conexión

## Requisitos

- Windows PowerShell / Consola de Visual
- Python 3.11 o compatible
- Node.js y npm
- Dependencias Python instaladas en `.venv`
- Dependencias JavaScript instaladas en `frontend/node_modules`

## Levantar el backend

Desde la raíz del proyecto:

```cmd
.venv\Scripts\Activate.ps1
cd backend
python api_server.py
```

El API queda disponible en:

```text
http://localhost:8000
```

Comprobación de salud:

```powershell
Invoke-WebRequest http://localhost:8000/health
```

Si el entorno virtual todavía no tiene las dependencias entonces ejecutar esto en la raíz:

```cmd
pip install -r backend\pipeline\requirements.txt
pip install fastapi uvicorn python-multipart
```

## Levantar el frontend

Abrir otra terminal y ejecutar desde la carpeta del frontend. La raíz del proyecto no contiene `package.json`.

```powershell
Set-Location .\frontend
npm install
npm run dev -- --host 0.0.0.0
```

La interfaz queda disponible en:

```text
http://localhost:5173
```

El script `npm run dev` ejecuta primero la sincronización de archivos de salida y después inicia Vite. La aplicación visual consume directamente el API local.

## Tecnología del frontend

- React 19 para la composición de la interfaz.
- Vite 8 para desarrollo y compilación.
- JavaScript/JSX.
- Tailwind CSS 4 mediante `@tailwindcss/vite`.
- CSS propio en `frontend/src/index.css` para el tema, layout, navegación y responsive.
- `lucide-react` para iconos.
- Recharts para visualizaciones disponibles en los componentes.

Archivos visuales principales:

- `frontend/src/App.jsx`
- `frontend/src/index.css`
- `frontend/src/components/`

## Comunicación entre frontend y backend

La configuración de las rutas se encuentra en:

```text
frontend/src/config/dataConfig.js
```

La base del API es:

```text
http://localhost:8000
```

### Analizar un video

```http
POST /api/videos/analyze
```

El frontend envía el video como `multipart/form-data`, usando el campo `file`:

```js
const formData = new FormData();
formData.append('file', selectedFile);
```

La solicitud es realizada desde:

```text
frontend/src/App.jsx
```

El backend guarda el archivo, ejecuta el pipeline y devuelve las métricas de la ejecución actual junto con la ruta del heatmap.

### Consultar el último análisis

```http
GET /api/videos/latest
```

Este endpoint devuelve el último resultado guardado por el backend. La interfaz actual inicia vacía y actualiza sus paneles con la respuesta del análisis que se acaba de ejecutar.

### Obtener el heatmap

```http
GET /api/videos/heatmap
```

Devuelve `heatmap.png` generado por el pipeline. El frontend añade un identificador de análisis a la URL para evitar que el navegador reutilice el heatmap anterior.

### Obtener archivos de salida

```http
GET /api/videos/output/{filename}
```

Sirve archivos existentes dentro de `backend/pipeline/output/`.

## Flujo completo

1. El usuario selecciona un video en React.
2. React envía el archivo al endpoint `POST /api/videos/analyze`.
3. FastAPI guarda el video en `backend/pipeline/uploads/`.
4. FastAPI ejecuta `backend/pipeline/src/pipeline.py`.
5. El pipeline genera métricas, eventos, conteos y heatmap en `backend/pipeline/output/`.
6. FastAPI devuelve el resultado JSON.
7. React actualiza KPIs, estado por góndola, embudo, alertas y heatmap.

## Multiprocessing y Apache Spark

### Multiprocessing: varios videos en paralelo

El endpoint `POST /api/videos/analyze-batch` ejecuta un pipeline independiente por video con `ProcessPoolExecutor`. El worker está definido a nivel de módulo y la API se inicia bajo `if __name__ == "__main__"` para que funcione con el método spawn de Windows. Si no se indica `max_workers`, usa `os.cpu_count()` limitado a la cantidad de videos del lote. Los fallos se devuelven por archivo y no cancelan los demás.

No requiere librerías adicionales: `concurrent.futures` forma parte de Python. En la interfaz, selecciona varios archivos en “Cargar video”; para probarlo directamente:

```powershell
curl.exe -F "files=@C:\ruta\video1.mp4" -F "files=@C:\ruta\video2.mp4" "http://localhost:8000/api/videos/analyze-batch?max_workers=2"
```

La respuesta incluye `procesamiento: "multiprocessing"`, el número de workers, la duración y un resultado independiente para cada video.

### Apache Spark: métricas históricas por góndola

`GET /api/spark/metricas` lee los `metricas_interaccion.json` archivados y calcula por góndola flujo total, dwell promedio ponderado por flujo, interacción y rechazo medios ponderados, rendimiento y cantidad de análisis. Cuando Spark funciona responde con `engine: "apache_spark"`; si PySpark, Java o el arranque de Spark falla, registra el motivo y calcula el mismo agregado con Python (`engine: "python_fallback"`) sin tumbar la API.

PySpark 3.5 está incluido en `backend/pipeline/requirements.txt`; usa JDK 17, la versión soportada por esa línea de Spark. Instala las dependencias desde la raíz y comprueba Java:

```powershell
pip install -r backend\pipeline\requirements.txt
java -version
```

Para probar el endpoint después de iniciar el backend:

```powershell
Invoke-RestMethod http://localhost:8000/api/spark/metricas
```

La pestaña “Rendimiento” consulta este endpoint al abrirse; muestra el motor utilizado y permite desplegar las métricas históricas agregadas. El dashboard y los paneles existentes conservan su orden.

## Comandos de validación

Frontend:

```powershell
Set-Location .\frontend
npm run build
npm run lint
```

Backend:

```powershell
.\.venv\Scripts\Activate.ps1
python -m py_compile backend\api_server.py
```

Para probar el endpoint con un video:

```powershell
curl.exe -F "file=@C:\ruta\al\video.mp4" http://localhost:8000/api/videos/analyze
```


.\.venv\Scripts\Activate.ps1
>> cd backend                                                                                        
>> python api_server.py