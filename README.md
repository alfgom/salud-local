# Salud Local

Asistente personal de salud **local para macOS Apple Silicon**. Combina un historial estructurado, documentos originales, cálculos reproducibles y una interpretación opcional de Ollama. Es un MVP funcional para preparar consultas, **no un dispositivo médico, diagnóstico ni sistema de decisión clínica**. No se ha validado clínicamente.

## Repositorio público y privacidad

Solo se publican código, documentación y ejemplos sintéticos. Las bóvedas, originales personales, claves, exportaciones y entornos locales están excluidos. Lee [CONTRIBUTING.md](CONTRIBUTING.md) y activa los hooks antes de contribuir. La lista de publicación y las huellas de los ejemplos están en `public-files.json`.

## Abrir y usar

En una copia nueva, completa primero la instalación descrita más abajo. Si las dependencias ya están instaladas, abre **Salud Local.app**, junto a este archivo, con doble clic. No muevas la app fuera de esta carpeta: es un lanzador del proyecto. Alternativa: doble clic en **Abrir Salud Local.command**. Solo hace falta una acción; ambos inician servidor, interfaz y una instancia privada de Ollama.

La interfaz se abre en **http://127.0.0.1:8765**. Se utiliza la dirección numérica de forma deliberada: `localhost` como Host se rechaza. Para detener los procesos, pulsa **Cerrar aplicación** en el lateral. Cerrar la pestaña no detiene el servidor. Una segunda apertura vuelve a la interfaz sin duplicar procesos.

1. En la bienvenida comprueba Ollama, ubicación de la bóveda y aislamiento de red. Puedes configurar una contraseña o continuar con acceso directo.
2. Explora los datos sintéticos. La demostración también pasa por la pantalla de revisión: verifica y confirma las 36 medidas.
3. Mira Inicio y Datos, las gráficas y sus fuentes. Genera una Health Review con o sin IA.
4. Antes de usar datos reales, entra en **Privacidad**, borra el perfil de demostración y configura contraseña. La app no mezcla automáticamente la demo con un perfil existente.
5. Importa documentos, corrige las propuestas y confirma solo las entradas contrastadas. La revisión siempre es obligatoria, incluso cuando no aparecen errores.

No se han utilizado datos médicos reales durante el desarrollo.

## Instalación en otro Mac

Requiere macOS Apple Silicon, Python 3.13, Ollama y al menos un modelo descargado. Baseline probado aquí: `qwen3.5:9b` (aproximadamente 6,6 GB de pesos). Se recomienda cerrar otras cargas pesadas en un equipo de 16 GB.

Copia el proyecto sin `.venv` ni perfiles personales. Abre **Instalar dependencias.command** una vez con conexión para instalar las versiones de `requirements.txt`. Instala Ollama desde su distribución oficial y descarga el modelo durante esta fase de preparación. Opcionalmente instala Tesseract para OCR (`brew install tesseract`); aquí está instalado con idioma inglés. Después todo el runtime funciona sin conexión.

Comando único alternativo, desde la carpeta del proyecto:

```sh
.venv/bin/python launch.py
```

Para instalación completamente offline en otro Mac, prepara previamente un repositorio de wheels compatibles con su Python/arquitectura y copia los modelos de Ollama. El lanzador **no instala ni actualiza dependencias ni descarga modelos**. Los fallos de Ollama no impiden importar o generar revisiones descriptivas sin IA.

## Arquitectura

```text
Navegador · recursos propios · CSP · 127.0.0.1:8765
                     │ sesión HttpOnly + CSRF + origen/Host
             FastAPI / Python, un proceso
          ┌──────────┼────────────────┐
          │          │                │
   Parser limitado   SQLite RAM      Cálculos Python
   PDF / OCR / CSV   instantánea     series, medias,
   / JSON / imagen   cifrada         porcentajes, MAD
          │          │                │
     Revisión humana → documentos + medidas confirmadas
                     │
        Vectores léxicos locales en SQLite
                     │
         Contexto acotado + evidencias literales
                     │
   Ollama privado · 127.0.0.1:11435 · sin cloud
   general → crítico opcional → síntesis opcional
                     │
     Health Review versionado y chat secundario
```

El frontend usa HTML/CSS/JavaScript propios, sin compilación, dependencias de frontend, fuentes remotas, CDN, analytics ni almacenamiento del historial en el navegador. El servidor sirve todos los recursos. FastAPI tiene telemetría nativa explícitamente desactivada, sin exportadores.

### Datos y persistencia

Ubicación predeterminada: `~/Library/Application Support/SaludLocal`. Esta ruta evita el directorio Documentos habitualmente sincronizado con iCloud. No configures sincronización externa sobre la bóveda ni sobre sus copias. `SALUD_DATA` permite cambiar la ubicación al arrancar; no apuntes a una carpeta compartida o sincronizada.

- `vault.bin`: instantánea SQLite cifrada. Tablas: documentos, observaciones, registros (medicación, condiciones, notas, prevención), fragmentos y vectores, revisiones, chat y configuración.
- `originals/<uuid>.bin`: originales cifrados y autenticados. Nombres internos generados, nunca rutas suministradas por archivos.
- `key.json`: clave Fernet en modo acceso directo, o clave envuelta mediante Scrypt y la contraseña local.
- `process.lock`: bloqueo técnico de instancia, sin datos clínicos.

SQLite funciona en memoria. No genera archivos SQLite, WAL, diarios ni índices clínicos en claro. Se serializa y cifra al persistir mediante archivo temporal **ya cifrado**, `fsync` y sustitución atómica de cada archivo. Esta solución sencilla privilegia auditabilidad sobre volumen: una bóveda muy grande aumentará el tiempo y memoria de cada escritura. Adecuada para un historial personal moderado; no para millones de muestras de wearables sin agregación previa.

Se conservan original, extracción inicial, propuesta normalizada y valores revisados, con fecha y ubicación. Una duplicación exacta del documento se rechaza por SHA-256. Las medidas con misma fecha, indicador, valor y unidad se deduplican; puede colapsar mediciones idénticas genuinas del mismo día, limitación explícita del esquema diario inicial.

### Importaciones

PDF con texto, PDF escaneado, PNG/JPEG, CSV UTF-8 y JSON. Límites: 10 MB, 40 páginas PDF, hasta 8 páginas escaneadas, 20 megapíxeles por imagen, 2000 medidas y 200 registros por archivo. El parser vive en un subproceso con timeout de 65 segundos, CPU limitada y monitor de RSS (~1 GB). Los procesos del grupo se terminan si exceden el timeout; las imágenes de OCR se reducen a 2200 píxeles por lado. Se limita también el texto extraído. El monitor de memoria es una defensa adicional, no una garantía contra picos entre muestreos.

Los uploads multipart se mantienen en RAM hasta el cifrado. El parser y Tesseract reciben contenido por pipes, no por archivos temporales. No se ejecutan macros, JavaScript, acciones PDF, adjuntos ni código incrustado. No se abren enlaces del documento. Los originales se descargan como adjuntos, nunca se incrustan como contenido activo de la interfaz.

Extracción deliberadamente conservadora: etiquetas reconocidas, valor y unidad en una misma línea, fecha ISO inequívoca en la página. Los PDF de tablas complejas o formatos no reconocidos pueden requerir entrada manual. El OCR instalado es inglés; revisa signos, decimales, unidades y acentos. No se realiza extracción de imágenes con un LLM. No se extraen diagnósticos ni medicación automáticamente del texto libre: se conserva como evidencia y se pueden añadir registros manualmente en la revisión.

Catálogo inicial de medidas: glucosa, HbA1c, LDL, HDL, triglicéridos, peso, presión sistólica/diastólica, sueño, pasos y frecuencia cardiaca. Otros análisis se pueden conservar como documentos y notas recuperables. Para convertirlos en series, hay que ampliar el catálogo auditado `app/analytics.py`; el sistema nunca fuerza un resultado desconocido a un indicador distinto.

CSV:

```csv
date,metric,value,unit,note
2026-06-15,glucose,98,mg/dL,Ejemplo sintético
2026-06-15,weight,77.2,kg,Ejemplo sintético
```

JSON: lista con los mismos campos, o `{ "observations": [...], "records": [...] }`. Un registro contiene `kind` (`medication`, `condition`, `note`, `prevention`, `lab_result`), `title`, `date` ISO y `detail`. `lab_result` conserva un resultado literal revisado, separado de las medidas numéricas. Ejemplos completos en `examples/`.

Fechas ambiguas y futuras, valores no finitos, unidades incompatibles e indicadores desconocidos bloquean la confirmación. Las envolventes de valor son controles amplios de plausibilidad de formato, **no intervalos de referencia clínica**. Conversión explícita mmol/L → mg/dL para glucosa, LDL/HDL y triglicéridos, con factor registrado. Para un dato raro pero real fuera de esas envolventes, consérvalo como nota y consulta su significado; no alteres el valor para que pase la validación.

### Cálculos, RAG e informes

Python ordena y agrupa medidas por indicador y día, calcula media diaria, cambio absoluto y porcentaje entre primera/última fecha. Si el valor inicial es cero, no inventa un porcentaje. Outliers descriptivos: puntuación robusta basada en mediana y MAD, mínimo cinco días, umbral 3,5, sin outliers si MAD es cero. No son alertas clínicas. Gráficas y tablas permiten consultar valores y fuentes.

El RAG inicial usa fragmentos solapados y vectores léxicos de 512 dimensiones mediante hashing estable, almacenados **dentro de la bóveda cifrada**. Es búsqueda vectorial local por coincidencia léxica, no embeddings semánticos médicos; puede perder sinónimos o contexto. Cada resultado mantiene documento y ubicación. No hay guías públicas preinstaladas ni afirmaciones respaldadas por ellas. La interfaz documenta estas limitaciones; puede ampliarse el recuperador manteniendo su interfaz y almacenamiento local.

Cada Health Review conserva su resultado y modelos usados. Incluye resumen, cardiovascular, metabólico, sueño, actividad, medicación, prevención, temas a vigilar, información faltante, preguntas y diferencias desde el anterior. Separación explícita: **DATO, CÁLCULO, EVIDENCIA, INTERPRETACIÓN, HIPÓTESIS, RECOMENDACIÓN PARA CONSULTAR e INCERTIDUMBRE**. Las cuatro últimas categorías de IA siempre se etiquetan como generadas y no verificadas. La referencia acredita procedencia, no corrección clínica. Se rechazan IDs de fuente inventados, pero un ID válido no asegura que la fuente implique la conclusión.

### Modelos y presupuesto de memoria

La aplicación usa una instancia separada de `ollama serve`, comparte los pesos ya instalados y no modifica tu instancia habitual. Puerto fijo 11435, `OLLAMA_NO_CLOUD=1`, `OLLAMA_MAX_LOADED_MODELS=1`, `OLLAMA_NUM_PARALLEL=1`, contexto 8192, `keep_alive=0` y serialización de trabajos. El adaptador no permite URLs de modelo externas, redirecciones ni auto-pull. Se comprueba que el modelo figure como instalado localmente y no sea remoto.

Baseline probado: Qwen 3.5 9B. Configuración permite elegir general, crítico y síntesis entre modelos instalados. Gemma 4 12B y MedGemma 1.5 4B quedan como candidatos: **no se descargaron ni se verificó su calidad/compatibilidad aquí**, y no se inventan tags. Instala por separado una versión compatible con Ollama para que aparezca. Puedes comparar revisiones históricas generadas con distintos modelos. El rol «crítico médico» no equivale a un especialista ni convierte otro modelo en clínicamente validado.

La secuencia descarga cada modelo antes del siguiente y no mantiene tres modelos simultáneamente. Un proceso Ollama ajeno a esta aplicación puede seguir consumiendo memoria; cierra otras sesiones pesadas si hay presión de RAM. Se usa contexto acotado: agregados longitudinales, registros limitados y fragmentos recuperados. No se envía toda la bóveda al modelo. Los cálculos nunca se solicitan al LLM. Sus afirmaciones con dígitos o expresiones de porcentaje se omiten mediante un filtro conservador; el chat muestra por separado los valores, diferencias con unidad y porcentajes de Python. Las respuestas históricas también se filtran al mostrarse. Este filtro reduce errores numéricos, pero no valida la semántica del resto de la interpretación. El chat guarda preguntas y respuestas; cada consulta vuelve a recuperar contexto, sin depender de una conversación infinita.

## Seguridad y privacidad

El lanzador aplica un perfil de aislamiento de macOS (`sandbox-exec`) que deniega red externa al servidor y a sus descendientes (Ollama, parser, OCR). Solo permite loopback. Adicionalmente, un audit hook Python bloquea conexiones salvo `127.0.0.1:11435`, DNS, UDP saliente y escucha en interfaces externas. CSP permite recursos y conexiones únicamente del propio origen; se comprueban Host, Origin, `Sec-Fetch-Site`, cookie HttpOnly SameSite Strict y cabecera anti-CSRF. No hay CORS permisivo.

Arrancar `uvicorn` directamente evita el perfil del lanzador: **usa siempre la app o `launch.py`**. `sandbox-exec` es una interfaz de macOS antigua; su disponibilidad futura no se puede garantizar. El lanzador falla si no puede ejecutarla, en vez de continuar silenciosamente con menos protección.

Fernet proporciona cifrado autenticado; contraseña derivada con Scrypt. La clave protegida y la contraseña son necesarias para restaurar. **No hay recuperación si pierdes la contraseña.** Sin contraseña, la clave está junto a los datos (permisos 0600, carpeta 0700): protege ante lectura accidental, no ante otro proceso de tu misma cuenta. Activar contraseña invalida sesiones previas. El timeout se aplica en servidor y borra la vista del navegador; se aplaza durante un trabajo activo para guardar su resultado.

No hay logs clínicos, logs de acceso HTTP ni volcados de respuesta de Ollama. Los mensajes técnicos son genéricos. El navegador y el sistema operativo no son controlados íntegramente por la aplicación: extensiones, malware, captura de pantalla, swap, crash dumps, backups y una cuenta comprometida quedan fuera de esta garantía. Activa FileVault, protege la sesión macOS y evita extensiones con acceso a la página. La aplicación no inspecciona ni modifica tus ajustes globales.

### Corregir errores de extracción sin compartir el informe

En **Importar → Revisar extracción → Descargar diagnóstico técnico** obtienes `salud-local-diagnostico.json`. Para un fallo que impida importar, usa **Privacidad → Descargar diagnóstico técnico**. La descarga requiere la sesión local y no se envía automáticamente. Puedes abrir el JSON y revisarlo antes de compartirlo para soporte.

El esquema permite exclusivamente códigos predefinidos, versión del extractor, formato y contadores técnicos: páginas/OCR, propuestas, etiquetas no reconocidas, fechas detectadas o ambiguas y errores de validación. No incluye nombres, fechas clínicas, valores, indicadores concretos, texto, rutas, IDs, huellas del documento, modelo ni mensajes/stack traces de excepciones. Se construye desde una lista permitida, no intentando ocultar nombres dentro de texto médico. Los contadores describen la estructura de un archivo; no prometemos anonimato absoluto ni que basten para reproducir todos los errores. No añadas capturas ni originales al reporte.

Las últimas 50 extracciones, incluidos fallos del parser, se guardan dentro de `vault.bin`, cifradas. Cada documento conserva también su último diagnóstico. **Privacidad → Borrar trazas técnicas** elimina ambos; borrar un documento elimina sus eventos; borrar el perfil elimina todo. El JSON descargado queda sin cifrar fuera de la bóveda y debes eliminarlo por separado si lo deseas. Las descargas y capturas nunca deben entrar en Git.

Los documentos importados con versiones anteriores no tienen trazas retroactivas. Abre un documento **pendiente** y pulsa **Volver a extraer este documento** para aplicar el nuevo extractor y generar un diagnóstico. Se sustituyen las propuestas y cambios sin confirmar, con aviso previo; el original permanece y nada se incorpora automáticamente. Los documentos confirmados no se reprocesan mediante este botón.

El extractor propone fechas ISO o DD/MM/AAAA bajo una etiqueta de fecha de muestra en español. Fechas sin contexto que puedan leerse como día/mes o mes/día se dejan vacías. Una fecha de muestra única puede aplicarse a otras páginas; fechas de muestra contradictorias requieren revisión. Admite aclaraciones de suero/plasma y columnas PDF mediante extracción de disposición. No equipara resultados de orina a glucosa sérica, ni convierte desigualdades en valores exactos.

El catálogo contiene 41 indicadores: las series iniciales de salud diaria y metabolismo, colesterol total, hemograma (recuentos absolutos separados de porcentajes), creatinina/urato, enzimas hepáticas, hierro/ferritina y CEA/PSA. No calcula decisiones clínicas ni recomienda solicitar marcadores por incluirlos en el catálogo. Los indicadores nuevos tienen límites técnicos amplios, no intervalos clínicos. Las unidades se contrastan con el catálogo; `x10³/mm³` y `10^3/µL`, por ejemplo, son grafías equivalentes y se normalizan sin alterar la cifra. Exponentes incompatibles y unidades ausentes requieren corrección. No se añaden conversiones inferidas de valores ni rangos impresos.

Resultados cualitativos, orina y etiquetas fuera del catálogo se mantienen como evidencia documental. El panel de alcance distingue etiquetas desconocidas, resultados cualitativos en etiquetas conocidas, muestras excluidas, formatos no reconocidos y unidades pendientes. El diagnóstico versión 4 separa validaciones de resultados acotados de otros errores numéricos y sitúa etiquetas numéricas desconocidas dentro/fuera de una sección de orina. Solo exporta contadores, nunca las etiquetas ni sus resultados. Las versiones anteriores siguen legibles.

Sus contadores son aproximados, no un recuento clínico completo: pueden incluir cabeceras y omitir filas difíciles de reconocer. Describen las propuestas de la extracción original; no representan los cambios manuales ni el estado final de la confirmación. No se amplía el catálogo automáticamente a partir de una etiqueta desconocida.

Para un resultado con `<`, `>`, `≤` o `≥`, pulsa **Conservar resultado literal** en su fila. Se prepara un registro `lab_result` con la expresión, unidad, fecha y ubicación; sigue pendiente de tu cotejo y confirmación. La fecha debe ser válida. El registro aparece como **EVIDENCIA** en Datos y en **Otros resultados de laboratorio** del Health Review, con enlace al documento. Se excluye de medias, porcentajes, outliers y gráficos numéricos. No sustituyas un límite por el número que aparece después del signo. Si prefieres, puedes retirar la propuesta y mantener el original. Las nuevas series cuantitativas aparecen también en las áreas de hematología y función renal/hepática del Health Review.

## Copia y recuperación

En **Privacidad → Descargar copia completa** se exportan bóveda, originales y clave como ZIP sin compresión. Si has activado contraseña, sigue siendo necesaria; si no, **la copia contiene la clave en claro**. Activa contraseña antes de exportar una copia sensible. No compartas ni sincronices copias sin decidirlo conscientemente.

Para recuperar desde la UI: usa un perfil vacío, introduce la contraseña de la copia (si existe) y selecciona ZIP, hasta 10 MB. Se validan rutas, tamaños expandidos, ratios, duplicados, estructura SQLite, autenticidad criptográfica y originales antes de reemplazar el perfil. No se usa extracción ZIP genérica. Si la contraseña o la copia fallan, el perfil existente se conserva.

Para una copia mayor: cierra la aplicación, conserva una copia del directorio actual, abre el ZIP que **tú exportaste y controlas**, y coloca `key.json`, `vault.bin` y la carpeta `originals` juntos en el directorio de datos. No mezcles claves de copias distintas. No abras archivos médicos de una copia no fiable fuera de los controles de la aplicación. Reinicia y desbloquea. Los archivos tienen sustitución atómica individual, no transacción de directorio completa durante la restauración: conserva el ZIP intacto por si un corte de energía interrumpe el reemplazo.

**Borrar perfil** elimina base, clave, originales, vectores, revisiones, chats y ajustes, y crea una bóveda vacía. **Borrar documento** elimina también revisiones y chat derivados para no conservar restos de ese documento. Ninguna de las acciones borra exportaciones, snapshots APFS, Time Machine, archivos originales externos, cachés del sistema o memoria de otros procesos. No se promete borrado físico seguro en SSD.

## Pruebas

Desde la carpeta del proyecto:

```sh
.venv/bin/python -m pytest -q
.venv/bin/python tests/check_macos_network.py
```

La suite usa perfiles temporales y datos sintéticos: validación de fechas/unidades/valores, porcentajes y outliers, mismo día y divisor cero, extracción PDF/OCR, no consolidación automática, duplicados, enlaces de origen, revisión/chat deterministas, cifrado/contraseña, timeout, sesiones, exportar/restaurar/borrar, archivos maliciosos, tamaño, traversal, egress Python, secuencia del adaptador y rechazo de citas inventadas. La comprobación macOS prueba TCP, UDP y un proceso nativo hijo bajo el mismo perfil, sin datos de salud.

Las pruebas de modelos con dobles verifican el contrato; no prueban exactitud clínica. Además se realizó una revisión real con Qwen 3.5 9B y datos sintéticos. Consulta `VALIDACION.md` para el estado observado. Las pruebas no sustituyen una auditoría independiente ni validación clínica.

## Límites conocidos y siguientes extensiones

- Catálogo estructurado limitado a 41 indicadores. Resultados cualitativos, orina y otras determinaciones siguen como evidencia documental; no se garantiza una extracción completa.
- OCR inglés y heurísticas sencillas; no garantiza comprensión de tablas, rangos de referencia ni manuscritos.
- RAG léxico, sin guías ni embeddings semánticos. La ventana de contexto puede omitir información.
- No cálculo de riesgo cardiovascular, recomendaciones individualizadas de cribado, comprobación de interacciones, diagnóstico ni urgencias.
- Datos diarios sin hora ni identificador de dispositivo; dos valores idénticos en el mismo día se consideran duplicados.
- No integración directa con Apple Health; acepta exportaciones previamente convertidas a CSV/JSON del esquema documentado.
- Un solo perfil activo, un solo trabajo de IA, sin cola persistente ni reanudación tras cerrar. Los originales y revisiones ya guardados persisten.
- Aplicación local sin firma/notarización ni instalador distribuible. Es un proyecto ejecutable y auditable, no una versión comercial terminada.

Referencias técnicas utilizadas en desarrollo: [API Chat de Ollama](https://docs.ollama.com/api/chat), [configuración de Ollama](https://docs.ollama.com/faq). Estas páginas **no se consultan en runtime**.
