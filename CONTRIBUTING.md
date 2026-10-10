# Desarrollo público sin datos personales

Este repositorio contiene código y ejemplos inventados. Nunca adjuntes informes reales, capturas de tu perfil, claves, bóvedas cifradas, copias de seguridad ni respuestas de IA basadas en tu salud a commits, issues o pull requests. El cifrado no convierte un archivo privado en material publicable.

Los datos de la aplicación viven fuera del repositorio, en `~/Library/Application Support/SaludLocal`. No los copies al proyecto para depurar. Reproduce los problemas con los ejemplos sintéticos de `examples/` y perfiles temporales.

## Configurar los controles locales

Tras clonar:

```sh
git config core.hooksPath .githooks
```

Antes de publicar:

```sh
python3 scripts/check_publication.py --history
```

Los hooks revisan el índice antes de commit y el historial antes de push. GitHub Actions repite la comprobación sobre el contenido que ya ha llegado a GitHub: **CI no evita una filtración inicial**, por eso importan los controles locales. No uses `--no-verify` para saltártelos.

`public-files.json` enumera los archivos permitidos y las huellas SHA-256 de los ejemplos sintéticos revisados. Un nuevo archivo o cambio de fixture requiere revisión deliberada y actualización del manifiesto. Nunca actualices una huella para dar por bueno un documento real. La comprobación detecta rutas/formatos privados y patrones habituales de secretos; no puede reconocer todos los datos personales incrustados en código o texto. Revisa también el diff.

Ejecuta las pruebas solo con datos sintéticos. No se necesita Ollama para la suite automatizada. La comprobación de aislamiento de macOS está disponible por separado en `tests/check_macos_network.py`.

## Reportar un fallo de extracción

Comparte, si lo deseas, el diagnóstico técnico que ofrece la revisión o Privacidad, después de leer su JSON. Explica el tipo de problema sin identificar pacientes ni transcribir resultados. No añadas el archivo descargado al repositorio: utiliza sus códigos para construir una reproducción inventada. No solicites informes originales, texto extraído, capturas clínicas, backups ni claves. Si las trazas no bastan, reproduce el patrón de columnas, etiqueta o formato de fecha con datos sintéticos completamente nuevos.

`app/diagnostics.py` es la frontera de exportación: solo enums fijos y contadores enteros acotados. Todo nuevo campo requiere justificar que no contiene ni codifica datos clínicos o identificadores y probar su exclusión de contenido arbitrario. No añadas mensajes de excepción, stack traces, hashes de documentos, timestamps ni nombres de modelos al esquema. Las trazas se conservan cifradas; la descarga manual no implica permiso para publicarlas automáticamente.

## Si ocurre una exposición

Detén los pushes, retira el contenido público, revoca credenciales afectadas y limpia el historial y las copias accesibles. Un nuevo commit que borra el archivo no lo elimina del historial. No publiques el contenido expuesto al informar del incidente. La eliminación no garantiza retirar clones o copias que otros ya hayan hecho.
