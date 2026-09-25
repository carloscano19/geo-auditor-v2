# Reglas de trabajo en este repositorio

## Git
- Trabaja siempre en una rama nueva con nombre descriptivo. Nunca hagas commit ni push directamente a main.
- Haz merge a main solo cuando se te pida explícitamente.
- Cuando se pida un diff, ejecuta git diff en el terminal y pega la salida literal, sin resumir ni reescribir. Si hay archivos nuevos, usa git add -N antes para que aparezcan.
- Al terminar una tarea, informa del nombre de la rama, el hash del commit y la salida literal de git log --oneline -3.

## Calidad
- Ejecuta todos los tests del backend (pytest) antes de cada commit. Si alguno falla, no hagas commit y explica por qué.
- Si cambias el frontend, ejecuta npm run build antes del commit.
- Añade tests para cada bug corregido o funcionalidad nueva.
- No cambies pesos, umbrales ni reglas de puntuación que no se hayan pedido explícitamente.

## Código
- Los patrones lingüísticos van centralizados en backend/src/utils/lang_patterns.py, siempre en inglés y español.
- Todas las explicaciones y recomendaciones que devuelve el backend van en inglés.
- La versión de la app sale únicamente de settings.app_version.
- No escribas claves de API ni secretos en el código: van en variables de entorno.

## Informes
- No afirmes que algo está hecho sin haberlo verificado ejecutándolo.
- Si algo no se ha podido hacer o hay dudas, dilo claramente en lugar de dar por supuesto.
