// `tab` indica qué pestaña del tablero debe estar activa para que el
// elemento de este paso sea visible (las pestañas ocultas usan `hidden`,
// así que el tour tiene que cambiar de pestaña antes de medir el target).
// `vista: null` significa "no importa" salvo que se fuerza 'tablero' al
// abrir el tour, porque ningún paso vive en la vista de Escena 3D.
export const TOUR_STEPS = [
  {
    target: '[data-tour="welcome"]',
    title: 'Bienvenido a GondHawk',
    content: 'GondHawk transforma el video de una superficie comercial en métricas útiles para entender el comportamiento alrededor de las góndolas.',
  },
  {
    target: '[data-tour="upload-video"]',
    tab: 'cargar',
    title: 'Carga tu video',
    content: 'Selecciona el video que quieres analizar. A partir de este archivo GondHawk genera las métricas de la sesión.',
  },
  {
    target: '[data-tour="analysis-options"]',
    tab: 'cargar',
    title: 'Configura el análisis',
    content: 'Puedes detectar las zonas automáticamente y elegir cuántos frames analizar. Usar todos los frames ofrece la mejor precisión.',
  },
  {
    target: '[data-tour="start-analysis"]',
    tab: 'cargar',
    title: 'Inicia el análisis',
    content: 'Cuando tengas un video seleccionado, usa este botón para comenzar el procesamiento. El tour no ejecutará esta acción por ti.',
  },
  {
    target: '[data-tour="metrics"]',
    tab: 'cargar',
    title: 'Métricas principales',
    content: 'Aquí verás personas detectadas, permanencia media, tasa de interacción y tasa de rechazo del análisis actual.',
  },
  {
    target: '[data-tour="heatmap"]',
    tab: 'video',
    title: 'Mapa de calor',
    content: 'El mapa de calor permite identificar visualmente las zonas con mayor y menor flujo alrededor de la superficie comercial.',
  },
  {
    target: '[data-tour="store-map"]',
    tab: 'video',
    title: 'Mapa de tienda',
    content: 'Esta vista cenital muestra la distribución de las zonas de la tienda y permite visualizar el recorrido de las personas durante el análisis.',
  },
  {
    target: '[data-tour="interactions"]',
    tab: 'rendimiento',
    title: 'Embudo de interacción',
    content: 'Este embudo resume el recorrido físico: personas que pasan, se detienen, toman un producto, lo devuelven o generan una posible conversión.',
  },
  {
    target: '[data-tour="performance"]',
    tab: 'rendimiento',
    title: 'Rendimiento por góndola',
    content: 'Compara el flujo, dwell time, interacción, rechazo y estado de cada góndola para detectar oportunidades de mejora.',
  },
  {
    target: '[data-tour="recommendations"]',
    tab: 'rendimiento',
    title: 'Recomendaciones',
    content: 'Aquí aparecen recomendaciones generadas a partir de las métricas del análisis para apoyar decisiones de distribución y space management.',
  },
  {
    target: '[data-tour="reports"]',
    tab: 'detalle',
    title: 'Descarga tus reportes',
    content: 'Después de cargar un análisis podrás descargar sus resultados en PDF, Excel o Word. Si todavía no hay un análisis disponible, este paso se omite.',
  },
  {
    target: '[data-tour="history"]',
    tab: 'historial',
    title: 'Historial',
    content: 'Consulta análisis guardados anteriormente y vuelve a abrirlos cuando necesites revisar sus resultados.',
  },
  {
    target: null,
    tab: 'cargar',
    title: '¡Listo!',
    content: 'Ya conoces las principales funciones de GondHawk. Ahora puedes explorar los resultados y analizar el comportamiento alrededor de las góndolas.',
  },
];
