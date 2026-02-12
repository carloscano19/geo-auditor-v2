---
trigger: always_on
---

Reglas y Buenas Prácticas de Desarrollo
GEO-AUDITOR AI
Versión 2.0 - Sistema de Auditoría GEO/AEO con Optimización LLM
Autor: Equipo de Desarrollo GEO-AUDITOR AI

PRIME DIRECTIVE: Actúa como un Arquitecto de Sistemas de Análisis de Contenido AI-Ready. Tu objetivo es construir un sistema robusto, escalable y preciso que evalúe la citabilidad de contenido web en Large Language Models (ChatGPT, Gemini, Claude, Perplexity), sin sacrificar la velocidad de análisis ni la experiencia del usuario. Estás construyendo una plataforma de auditoría donde la precisión de detección, la escalabilidad multi-plataforma y la integridad de datos son críticas.

I. INTEGRIDAD ESTRUCTURAL Y ARQUITECTURA MODULAR
Separación Estricta de Capas (Análisis, Procesamiento, Presentación):
•	Capa de Análisis (Analysis Layer): Detectores NLP, scrapers, parsers de Schema.org. Esta capa solo extrae y estructura datos crudos.
•	Capa de Procesamiento (Processing Layer): Cálculo de scores, validación de E-E-A-T, mapping de claims a evidencias. Esta capa transforma datos en insights.
•	Capa de Presentación (UI Layer): Dashboard, visualizaciones, exportación de reportes. Esta capa solo renderiza resultados procesados.
•	Regla: Un módulo de scraping NUNCA calcula un score. Un componente de UI NUNCA ejecuta lógica NLP. La violación de esta regla rompe la testabilidad y escalabilidad.

Modularización por Dimensiones de Auditoría:
•	Cada una de las 10 dimensiones del SRS (Infraestructura Técnica, Metadata Intelligence, Estructura AEO, etc.) debe ser un módulo independiente con su propio detector/scorer.
•	Por qué: Si necesitamos ajustar el algoritmo de "Power Lead Detection", solo editamos el módulo PowerLeadDetector, sin tocar Claims Extraction o E-E-A-T scoring.
•	Estructura sugerida: /src/detectors/infrastructure.py, /src/detectors/metadata.py, /src/detectors/power_lead.py, etc.

Agnosticismo de APIs y Servicios Externos:
•	El sistema integra con OpenAI API, Anthropic API, Google Gemini API. NUNCA llamar directamente a estas APIs desde módulos de lógica.
•	Solución: Crear un wrapper genérico LLMClient con implementaciones específicas (OpenAIClient, AnthropicClient). Si OpenAI sube precios o cambiamos a otro proveedor, solo modificamos el wrapper.
•	Aplica lo mismo para scraping: BeautifulSoupScraper vs PlaywrightScraper, intercambiables sin romper dependencias.

Principio de Datos Inmutables en Pipelines:
•	Cada etapa del pipeline de análisis (scraping → parsing → scoring → rendering) debe producir nuevos objetos de datos, NO mutar los existentes.
•	Por qué: Permite rollback, debugging, y trazabilidad. Si un score es incorrecto, podemos reejecutar solo la etapa de scoring sin re-scrapear.
II. PROTOCOLO DE PRECISIÓN EN NLP Y DETECCIÓN DE SEÑALES
Regla de Ground Truth para Entrenamiento/Validación:
•	Antes de implementar cualquier detector NLP (Power Lead, Claims Extraction, E-E-A-T signals), crear un dataset etiquetado manualmente de al menos 100 páginas de prueba.
•	Criterios de aceptación del SRS exigen >90% precision/recall. No puedes validar sin ground truth.
•	Almacenar este dataset en /tests/fixtures/ con anotaciones en JSON (page_url, expected_power_lead, expected_claims[], etc.).

Extracción Conservadora de Claims (Bajo False Positive Rate):
•	El SRS requiere <5% false positives en detección de claims. Es preferible no detectar un claim débil que marcar incorrectamente una frase descriptiva.
•	Patrón de detección: Buscar verbos declarativos (aseverar, demostrar, evidenciar) + sujeto + objeto medible/verificable.
•	Rechazar: opiniones ("creemos que"), suposiciones ("puede que"), y fluff genérico ("el marketing digital es importante").

Detección Robusta de Schema.org y Structured Data:
•	No asumir que el Schema está en <script type="application/ld+json">. Verificar también: JSON-LD inline, microdata (itemprop), RDFa.
•	Usar librerías especializadas: extruct (Python) para extraer todos los formatos. No parsear manualmente con regex.
•	Validación: Después de extraer Schema, validar contra Schema.org validator. Si no pasa validación, marcar como "Schema presente pero inválido" (penalización menor).

Manejo de Errores en Scraping sin Romper el Pipeline:
•	Si una página retorna 404, timeout, o contenido bloqueado por CAPTCHA, NO fallar el análisis completo.
•	Estrategia: Usar patrón Try-Catch por dimensión. Si "Infraestructura Técnica" falla al verificar HTTPS, marcar score=0 para esa dimensión y continuar con las otras 9.
•	Logging detallado: Registrar cada error con contexto (URL, dimensión afectada, timestamp). Útil para debugging de clientes.
III. SISTEMA DE SCORING Y PESOS CALIBRADOS
Transparencia Total en Cálculo de Scores:
•	Cada score final debe ser explicable: "Tu página obtuvo 67/100 porque: Infraestructura=8/10, Metadata=9/10, Power Lead=0/10..."
•	Implementación: Devolver objetos ScoreBreakdown con campos dimension, raw_score, weight, contribution_to_total.
•	Nunca usar "magic numbers" en scoring. Cada peso debe estar en un config file centralizado: config/scoring_weights.json

Versionado de Algoritmos de Scoring:
•	Si ajustamos el peso de "Evidence Density" de 15 a 20 puntos, la comparación histórica se rompe ("¿por qué mi score bajó si no cambié nada?").
•	Solución: Guardar scoring_version en cada auditoría. Permitir re-scoring con algoritmo actual para comparar manzanas con manzanas.
•	En DB: tabla audits incluye campo scoring_algorithm_version (ej: "v2.0-feb2026").

Normalización de Scores para Comparabilidad Cross-Platform:
•	ChatGPT puede preferir H2s formulados como preguntas, mientras Gemini prioriza lists con datos numéricos. Cada plataforma tiene su "Citation Score" separado.
•	Implementación: Calcular score_chatgpt, score_gemini, score_perplexity con pesos específicos por plataforma, pero mantener un score_general (promedio ponderado).
IV. UX/UI: VISUALIZACIÓN DE AUDITORÍAS COMPLEJAS
Diseño de Dashboard Centrado en Accionabilidad:
•	Objetivo: El usuario debe saber QUÉ arreglar PRIMERO en menos de 10 segundos de mirar el dashboard.
•	Patrón: Mostrar las 3 dimensiones con peor score en la parte superior, con botones directos "Fix This" que llevan a guías específicas.
•	Evitar: Dashboards sobrecargados con 20 métricas sin jerarquía visual. Usar progressive disclosure (click para expandir detalles).

Evidence Map Interactivo (Claims ↔ Sources):
•	El SRS requiere que el usuario haga click en un claim y vea su evidencia linkada. Esto NO puede ser una lista estática de texto.
•	Implementación sugerida: Componente React con tooltips. Hover sobre "El 75% de usuarios prefieren X" → tooltip muestra "Source: study-url.com/research-2025".
•	Código de color: Claims con evidencia = verde, sin evidencia = rojo, evidencia débil (foros, blogs) = amarillo.

Comparador Side-by-Side (Antes vs Optimizado):
•	Cuando el sistema genera versión optimizada, mostrar diff visual estilo GitHub: verde=añadido, rojo=eliminado, amarillo=modificado.
•	Cada cambio debe tener tooltip explicando el "por qué": "Añadimos fecha visible en primeros 200 chars para mejorar Freshness Signal (+10 pts)".
V. GESTIÓN DE DATOS Y TRAZABILIDAD
Registro Histórico Completo de Auditorías:
•	Cada auditoría ejecutada debe guardarse en la BD con: timestamp, URL analizada, scores por dimensión, versión del algoritmo, contenido scrapeado (snapshot).
•	Por qué: Permite análisis de tendencias ("Mi score mejoró +15 pts en 3 meses"), debugging ("¿por qué esta auditoría falló?"), y compliance.

Q-Set Management y Auditorías Recurrentes:
•	El SRS incluye sistema de Q-Set (conjuntos de queries para auditorías mensuales). Esto debe ser configurable por usuario.
•	Implementación: Tabla q_sets con campos: project_id, queries[], frequency (monthly/weekly), platforms[] (ChatGPT/Gemini/etc).
•	Cron job ejecuta auditorías automáticamente y envía alertas si Citation Accuracy cae <90% o Share of Voice baja >10%.

Content Versioning para Detection de Decay:
•	El sistema debe detectar cuando una página no ha sido actualizada en >90 días (señal de decay). Necesita comparar versiones.
•	Solución: Guardar hash SHA-256 del contenido principal en cada auditoría. Si hash es idéntico durante 3 meses, disparar alerta de "Content Stale".
VI. ESTÁNDARES DE CÓDIGO Y TESTING
Cobertura de Tests Mínima por Módulo:
•	Módulos críticos (detectors NLP, scoring engine) requieren >85% code coverage.
•	Tests unitarios para cada detector: test_power_lead_detector.py, test_claims_extractor.py.
•	Tests de integración para pipeline completo: URL → scraping → parsing → scoring → output JSON.

Documentación Inline de Algoritmos Complejos:
•	Si implementas el algoritmo de "E-E-A-T Signal Detection", DEBES incluir docstring explicando: qué patrones NLP usa, por qué esos patrones, ejemplos de frases que detecta vs que no.
•	Formato: Google-style docstrings con secciones Args, Returns, Raises, Examples.

Control de Versiones y Branching Strategy:
•	Main branch: Código estable que pasa todos los tests.
•	Feature branches: feature/power-lead-detection, feature/claims-extraction. Un feature = un detector o dimensión.
•	Pull Requests deben incluir: descripción del cambio, tests añadidos, validación con ground truth dataset si aplica.
VII. PERFORMANCE Y ESCALABILIDAD
Target de Tiempo de Análisis: <60 Segundos por Página:
•	El SRS especifica <60s para páginas de hasta 5000 palabras. Esto incluye scraping + parsing + NLP + scoring.
•	Estrategia: Paralelizar detecciones independientes (Schema extraction y Claims extraction pueden correr simultáneamente).
•	Usar asyncio para scraping concurrente si auditamos múltiples URLs en un batch.

Caching Inteligente para Reducciones de Costos:
•	Si una URL fue auditada hace <24 horas y su contenido no cambió (mismo hash), reutilizar resultados cached.
•	Implementación: Redis para cacheo de resultados intermedios (parsed_content, extracted_claims) con TTL configurable.

Rate Limiting para Llamadas a APIs LLM:
•	OpenAI/Anthropic/Gemini tienen rate limits. Si ejecutamos auditoría mensual de Q-Set con 50 queries x 3 plataformas = 150 llamadas.
•	Solución: Implementar exponential backoff y queue system. Si hit rate limit, esperar y reintentar automáticamente.
VIII. SEGURIDAD Y PRIVACIDAD
Sanitización de URLs y Contenido Scrapeado:
•	Nunca ejecutar scripts embebidos de páginas scrapeadas. Usar parsers que solo extraen estructura (BeautifulSoup en modo lxml, NO html.parser).
•	Validar URLs antes de scrapear: rechazar URLs con protocolos no-HTTP (file://, javascript://).

Almacenamiento Seguro de API Keys:
•	NUNCA hardcodear API keys en código. Usar variables de entorno (.env file con .gitignore) o secret managers (AWS Secrets Manager, GCP Secret Manager).
•	Rotación periódica de keys cada 90 días.
IX. META-INSTRUCCIÓN DE AUTO-VALIDACIÓN
Antes de mergear cualquier feature o módulo nuevo, ejecuta esta checklist mental:
•	¿Respeta la separación de capas (Analysis/Processing/Presentation)?
•	¿Incluye tests unitarios con >85% coverage?
•	¿Está validado contra ground truth dataset?
•	¿Los scores son explicables y versionados?
•	¿El módulo falla gracefully sin romper el pipeline completo?
•	¿Está documentado con docstrings y ejemplos de uso?
•	¿Cumple con el target de performance (<60s por página)?
Si la respuesta a cualquiera es "No", refactorizar antes de integrar.


— Fin del Documento —

GEO-AUDITOR AI - Sistema de Auditoría GEO/AEO para Optimización de Citabilidad en LLMs
Versión 2.0 - Febrero 2026
