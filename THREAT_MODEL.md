# Modelo de amenazas · Salud Local

## Activos y límites de confianza

Activos: documentos originales, medidas, antecedentes/medicación, texto extraído, vectores, preguntas, informes, contraseña y clave. El navegador, backend, parser y Ollama son procesos distintos. Documentos importados, modelos y respuestas son entradas no fiables. El sistema operativo y la cuenta macOS forman parte de la base de confianza.

Objetivo: impedir que el runtime de la aplicación envíe datos a servicios externos, evitar consolidar extracciones inválidas y limitar el impacto de archivos o sitios maliciosos. No protege frente a administrador/malware con control del Mac ni demuestra exactitud médica.

| Amenaza / superficie | Mitigación implementada | Riesgo residual |
|---|---|---|
| Envío de datos a cloud por código, modelos o librerías | Perfil macOS que deniega red externa, heredado por hijos; Ollama privado sin cloud; audit hook Python; sin SDKs cloud | Sistema/navegador/extensiones fuera del árbol de procesos; vulnerabilidad del kernel; no ejecutar por rutas alternativas |
| Exposición a red LAN | Bind numérico exclusivo a 127.0.0.1; rechazo de otros Host; puertos privados | Otros procesos locales con acceso a la cuenta; UI sin contraseña opcional |
| Sitio malicioso que llama al servidor local / DNS rebinding | Host exacto, Origin, Sec-Fetch-Site, SameSite Strict, cookie HttpOnly, cabecera CSRF, sin CORS | Malware local puede enviar cabeceras falsas; contraseña reduce acceso casual, no sustituye aislamiento del SO |
| Robo del disco / copia del perfil | Bóveda y originales con Fernet, clave Scrypt envuelta si hay contraseña, permisos 0700/0600 | Sin contraseña la clave está accesible a la cuenta. Contraseñas débiles, swap/snapshots/backups; FileVault recomendado |
| XSS o contenido activo del documento | Escape de todos los textos, sin interpretación de Markdown/HTML del LLM, CSP estricta, originales solo adjuntos | Abrir un original descargado en otra aplicación sale del límite de confianza |
| Traversal y nombres manipulados | Originales con UUID, nombres normalizados, consultas parametrizadas, ZIP restore con whitelist estricta | Copias manipuladas mediante herramientas externas no pasan necesariamente por controles |
| Bombas ZIP/PDF, imágenes enormes, agotamiento de RAM/CPU | ZIP rechazado en ingesta, 10 MB por solicitud, límites de páginas/píxeles/texto, parser separado, CPU/timeout, monitor RSS, ratios expandidos al restaurar | Picos entre muestreos; fallos de librerías nativas; no es un sandbox de filesystem del parser |
| Ejecución de macros/adjuntos/scripts | Solo formatos permitidos y firmas PDF/imagen; no ejecutar acciones ni extraer adjuntos; OCR por pipes con argumentos fijos | Exploit de un parser nativo podría acceder al filesystem de la cuenta; actualizar dependencias y restringir fuentes |
| Archivos temporales clínicos en claro | Multipart solo RAM, pipes, SQLite RAM, persistencia cifrada | Swap, memoria y crash dumps del SO; no borrado criptográfico garantizado de memoria Python |
| Prompt injection y alucinaciones | Documentos delimitados como datos, sin herramientas del modelo, datos/cálculos separados, validación de categorías e IDs, interpretación marcada IA | Instrucción de sistema no es una defensa perfecta; una cita válida puede no sustentar el texto |
| Error clínico por fecha/unidad/transcripción | Confirmación humana obligatoria, validación estricta, sin autocompletar fecha dudosa, normalización explícita, datos originales accesibles | Humano puede confirmar un error; extracción incompleta; catálogo limitado; no validación médica |
| Fallo de energía o corrupción | Cifrado autenticado, snapshot individual atómico, exportación/restauración validada | Último cambio no persistido; reemplazo de varios archivos en restore no transaccional; conservar backup |
| Pérdida de contraseña | Avisos al configurar/exportar, clave envuelta, restauración con contraseña | Sin puerta trasera ni recuperación. Pérdida definitiva si no hay copia utilizable |
| Borrado incompleto | Borra tablas, originales, vectores, informes y chat; quita clave del perfil | SSD, snapshots, copias exportadas, documentos fuente fuera del perfil y memoria de otros procesos |
| Dependencia maliciosa / cadena de suministro | Versiones fijadas, instalación separada del runtime, código legible, sin recursos remotos | No hay auditoría independiente ni verificación reproducible de toda la cadena de distribución |

## Evidencias de comprobación

Tests de validación y no consolidación; carga de falsos PDF/MIME/ZIP; tamaño máximo y traversal; autenticación/timeout/CSRF/Host; snapshots cifrados y restauración con contraseña incorrecta sin reemplazar; bloqueo de conexiones Python; pruebas del perfil macOS con TCP, UDP y proceso nativo hijo. Se prueban con datos sintéticos.

## Prioridades antes de uso más amplio

Auditoría independiente, aislamiento más estricto del filesystem del parser, integración con Keychain o contenedor nativo, firma/notarización, pruebas con más formatos sintéticos, modelo semántico local evaluado, catálogo clínico versionado y validación clínica independiente. Ningún cambio futuro debe habilitar cloud, descargar modelos o incorporar guías automáticamente en runtime.
