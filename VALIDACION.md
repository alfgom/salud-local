# Validación del MVP

Comprobaciones realizadas el 29–30 de septiembre de 2026 con datos sintéticos. No se han usado documentos médicos reales ni se ha evaluado exactitud clínica.

## Resultado automatizado

**28 pruebas superadas**, última ejecución: 3,43 segundos. Un aviso de deprecación de Starlette sobre su cliente de pruebas; no afecta al runtime ni representa una prueba fallida.

Cobertura: fechas/unidades/valores, conversión mmol/L, tendencias, medias diarias, divisor cero, MAD, extracción PDF y OCR de imagen, confirmación obligatoria, duplicados, trazabilidad, Health Review y chat descriptivos, cifrado en reposo, contraseñas, timeout, invalidación de sesiones, copia/restauración/borrado, copia dañada o contraseña incorrecta sin sustituir el perfil, CSRF/Host/CSP, uploads maliciosos/tamaño/traversal, ausencia de temporales en claro y telemetría desactivada, bloqueo de conexiones Python, contrato de ejecución secuencial y rechazo de IDs de fuentes inventados.

## Aislamiento de red

La prueba independiente de macOS confirmó:

- TCP externo: denegado por macOS.
- UDP externo: denegado por macOS.
- Conexión externa desde un proceso nativo hijo: bloqueada.

Se verificó escucha únicamente en `127.0.0.1:8765` (Python) y `127.0.0.1:11435` (Ollama privado). No se modificó la instancia habitual de Ollama.

## Integración real y visual

- Primera ejecución, detección de cinco modelos instalados y OCR local.
- Importación del JSON sintético, revisión visual y confirmación de 36 medidas.
- Dashboard con seis series longitudinales; filtrado de LDL desde abril devuelve abril, mayo y junio.
- Navegación desde una medida hasta el documento original y texto extraído.
- Primera Health Review completada con **Qwen 3.5 9B**.
- Segunda Health Review completada mediante **Qwen 3.5 9B → Qwen 3.5 4B → Qwen 3.5 9B**. Los tres pasos constan en el informe y se ejecutaron secuencialmente.
- Comparación con la revisión anterior: ausencia de cambios correctamente reflejada cuando no se modifican los datos.
- Se observó la instancia Ollama sin modelos cargados después de la primera revisión.
- Persistencia del historial tras cerrar y arrancar de nuevo.
- Cierre desde la interfaz comprobado; se corrigió la reutilización del puerto al reabrir inmediatamente.
- Chat real con Qwen 3.5 9B y recuperación documental, guardado en el historial. La prueba detectó una confusión del modelo entre mg/dL y puntos porcentuales; se añadió un filtro numérico conservador, una prueba de regresión y una tabla separada de cálculos de Python. También se filtran las respuestas históricas al mostrarse.
- Recarga de la página durante un análisis: el trabajo activo y su progreso se recuperan.
- PDF sintético renderizado e inspeccionado visualmente, sin texto cortado.
- Interfaz inspeccionada visualmente; recursos propios, sin CDN ni tipografía remota.

## Estado de entrega

Proyecto con dependencias instaladas y lanzadores de un gesto para este Mac. La bóveda de demostración se conserva en `~/Library/Application Support/SaludLocal`, separada del código. La copia de desarrollo que estaba junto al proyecto se retiró. La demostración usa acceso directo sin contraseña; el usuario puede activar su propia contraseña en Configuración, sin que el desarrollador la conozca.

El baseline vuelve a ser Qwen 3.5 9B; la secuencia opcional queda disponible en Configuración. Gemma 4 12B y MedGemma 1.5 4B no están instalados y no se afirma que se hayan probado.

## Límites de esta validación

No es una auditoría independiente ni una certificación de ausencia de vulnerabilidades. Las pruebas de red comprueban controles concretos; no garantizan la seguridad de un sistema operativo comprometido, extensiones del navegador o copias externas. La extracción se probó con ejemplos simples, no con todos los formatos de laboratorio. El catálogo inicial contiene 11 indicadores, el OCR instalado es inglés y el recuperador usa vectores léxicos. La IA puede equivocarse aun citando una fuente existente. Véanse README y THREAT_MODEL para compromisos y riesgos residuales.

## Preparación para publicación · 10 de octubre de 2026

33 pruebas superadas, incluidas cinco comprobaciones de la barrera de publicación. Solo se autorizaron 35 archivos de código, documentación, configuración de desarrollo y cuatro ejemplos sintéticos. Los ejemplos tienen huellas SHA-256 en el manifiesto; los hooks están habilitados en esta copia local. La comprobación del historial se ejecuta antes de subir. No se incluyeron datos personales, bóvedas, claves, exportaciones ni entornos locales. GitHub Actions repite las comprobaciones con fixtures sintéticos.
