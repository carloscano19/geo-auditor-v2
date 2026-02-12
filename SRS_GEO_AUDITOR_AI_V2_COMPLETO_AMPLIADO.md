**DOCUMENTO DE ESPECIFICACIÓN DE REQUERIMIENTOS**

**GEO-AUDITOR AI**

*Sistema Avanzado de Auditoría GEO/AEO para Optimización de Citabilidad en LLMs*

**Versión 2.0 - Ampliada con Criterios de Citabilidad LLM**

|**Versión**|**2.0 - Criterios Ampliados**|
| :- | :- |
|**Fecha**|Febrero 2026|
|**Estado**|Especificación Completa con Benchmarks de Industria|
|**Tipo de Proyecto**|Aplicación Web de Análisis de Contenido AI-Ready con Citabilidad LLM|
|**Alcance**|Optimización para ChatGPT, Gemini, Claude, Perplexity, Microsoft Copilot|


# **NOTA IMPORTANTE SOBRE ESTA VERSIÓN**
Esta versión 2.0 del SRS ha sido significativamente ampliada con criterios específicos de citabilidad para Large Language Models (LLMs), basándose en investigaciones actuales de la industria sobre qué factores determinan que un contenido sea citado por motores de respuesta generativa como ChatGPT, Gemini, Claude y Perplexity.

Nuevos elementos incluidos en esta versión:

- Anatomía de página altamente citable para LLMs (criterios visuales y estructurales)
- Cambio de paradigma: de "rankings" a "citaciones" como métrica principal
- Criterios E-E-A-T (Experience, Expertise, Authoritativeness, Trustworthiness) operacionales
- Auditorías específicas por plataforma (ChatGPT, Gemini, Perplexity)
- KPIs específicos de GEO: Share of Voice en AI, Answer Coverage, Citation Accuracy
- Criterios de frescura y changelog para señalización continua
- Gobernanza de claims y gestión de evidencias
- Fase de distribución cross-platform para entrenamiento de modelos



Tabla de Contenidos

[Se generará automáticamente al abrir en Microsoft Word]


# **1. RESUMEN EJECUTIVO**
## **1.1. El Cambio de Paradigma: De Rankings a Citaciones**
La visibilidad online ya no se mide únicamente por posiciones en SERPs (Search Engine Results Pages). En 2025-2026, el éxito digital se define por la frecuencia con la que tu contenido es citado, sintetizado y presentado por motores de respuesta generativa como ChatGPT, Google Gemini, Claude, Microsoft Copilot y Perplexity AI.

Este documento especifica los requerimientos para GEO-Auditor AI, un sistema que evalúa contenidos no solo por su optimización SEO tradicional, sino por su capacidad de ser descubierto, comprendido, verificado y citado por Large Language Models (LLMs).
## **1.2. Propósito y Alcance Ampliado**
GEO-Auditor AI es una plataforma de análisis avanzado que evalúa contenido web mediante criterios científicos derivados de investigaciones sobre comportamiento de LLMs, incluyendo:

- Anatomía de Página Citable: Elementos visuales y estructurales que aumentan probabilidad de citación
- E-E-A-T Operacional: Implementación práctica de Experience, Expertise, Authoritativeness, Trustworthiness
- Fact Surface Audit: Mapeo de afirmaciones vs evidencias públicas verificables
- Citation Score: Puntuación predictiva de probabilidad de ser citado por LLMs específicos
- Platform-Specific Optimization: Recomendaciones diferenciadas para ChatGPT, Gemini, Perplexity
- Freshness Signals: Análisis de recencia y actualización continua
- Claim Governance: Sistema de trazabilidad de afirmaciones y fuentes
## **1.3. Métricas de Éxito en la Era GEO**
El sistema medirá el éxito mediante KPIs específicos de citabilidad:

|**KPI**|**Definición**|**Target Óptimo**|
| :- | :- | :- |
|**Share of Voice en AI**|% de queries en las que apareces citado|>40%|
|**Answer Coverage**|% de tus Q-set contestadas con tus fuentes|>60%|
|**Citation Accuracy**|% de citas que reflejan correctamente tu info|>95%|
|**Freshness Lead Time**|Días desde última actualización vs competencia|<30 días|
|**Evidence Density**|Claims con evidencia pública / Total claims|>80%|


# **2. FUNDAMENTOS CONCEPTUALES: QUÉ HACE QUE UNA PÁGINA SEA CITABLE**
## **2.1. Anatomía de una Página Altamente Citable para LLMs**
Basándonos en investigación de campo sobre qué páginas son citadas consistentemente por LLMs, hemos identificado los siguientes elementos estructurales críticos:
### **2.1.1. Elemento 1: Responde a una Pregunta Frecuente**
CRITERIO: El contenido debe abordar directamente una consulta común de usuarios.

- Implementación en el sistema:
- Detectar si el H1/título está formulado como pregunta o responde una pregunta implícita
- Verificar presencia de pregunta en primeras 100 palabras
- Comparar con datasets de "People Also Ask" y tendencias de búsqueda conversacional
### **2.1.2. Elemento 2: Fecha de Última Actualización Visible y Reciente**
CRITERIO: El contenido muestra señales claras de frescura y mantenimiento activo.

- Implementación en el sistema:
- Verificar presencia de "Actualizado: [fecha]" o "Last modified" visible en página
- Calcular días desde última actualización
- Penalización progresiva: -2 puntos por cada 30 días de antigüedad superior a 90 días
- Bonificación: +10 puntos si fecha está en primeros 200 caracteres
### **2.1.3. Elemento 3: Respuesta Clara Desde el Principio (Power Lead)**
CRITERIO: La respuesta directa debe aparecer en los primeros 150-200 caracteres del contenido principal.

- Implementación en el sistema:
- Extraer primeros 200 caracteres del body (excluyendo headers y metadata)
- Usar NLP para detectar si contiene: sujeto + verbo + objeto relacionado con el título
- Verificar ausencia de "fluff" introductorio ("En este artículo vamos a...")
- Score binario: 100 si cumple Power Lead, 0 si no
### **2.1.4. Elemento 4: Basado en Datos Originales**
CRITERIO: El contenido debe incluir datos propios, investigación original o encuestas verificables.

- Implementación en el sistema:
- Detectar frases como "según nuestro estudio", "encuestamos a X profesionales", "nuestros datos muestran"
- Identificar presencia de datasets descargables, gráficos con datos propios, metodología de investigación
- Bonificación: +20 puntos si incluye datos originales con metodología clara
### **2.1.5. Elemento 5: Firma de Autor Experto Clara**
CRITERIO: Atribución clara a un autor con credenciales verificables y bio pública.

- Implementación en el sistema:
- Verificar presencia de byline con nombre de autor
- Detectar link a bio del autor o perfil de LinkedIn/redes profesionales
- Verificar Schema Person con sameAs apuntando a perfiles externos
- Bonificación adicional si incluye foto y credenciales (PhDcertificaciones, años de experiencia)
### **2.1.6. Elemento 6: Información Estructurada y Específica**
CRITERIO: El artículo completo es fácil de escanear, con secciones H2/H3 claramente delimitadas.

- Implementación en el sistema:
- Contar número de H2 y H3 vs longitud del texto (ratio óptimo: 1 H2 cada 300-500 palabras)
- Verificar que cada H2 tenga al menos un párrafo de 50-150 palabras inmediatamente después
- Detectar uso de listas, tablas, o elementos de énfasis (negrita) para destacar conceptos clave
- Penalización: -5 puntos por cada "muro de texto" de >500 palabras sin subtítulos
### **2.1.7. Elemento 7: Datos Explorados desde Diferentes Ángulos**
CRITERIO: El contenido aborda el tema desde múltiples perspectivas, casos de uso o dimensiones.

- Implementación en el sistema:
- Detectar presencia de secciones como "Ventajas/Desventajas", "Casos de Uso", "Comparativa", "Análisis por Segmento"
- Verificar que el tema sea explorado con al menos 3 subtemas relacionados (Topic Cluster approach)
- Identificar uso de tablas comparativas, gráficos multi-dimensionales, o matrices de decisión


# **3. ARQUITECTURA DE EVALUACIÓN: 10 DIMENSIONES DE CITABILIDAD**
El sistema evolucionado evaluará contenido mediante 10 dimensiones ponderadas (vs las 7 originales), incorporando los nuevos criterios de investigación en citabilidad LLM.

|**Dimensión**|**Peso**|**Enfoque Principal**|
| :- | :- | :- |
|**1. Infraestructura Técnica**|12%|SSR/CSR, Crawlability, Renderizado|
|**2. Metadata y Schema**|8%|JSON-LD, dateModified, Schema completo|
|**3. Estructura de Respuesta (AEO)**|18%|H2 interrogativos, Power Lead, Regla de 60|
|**4. Densidad de Evidencia**|15%|Fact Surface, Claims vs Proofs, Datos originales|
|**5. Autoridad y E-E-A-T**|15%|Authorship, Credentials, First-party data|
|**6. Identificación de Entidades**|8%|Marca + Tema en primeros 150 chars, NER|
|**7. Frescura y Actualización**|8%|dateModified, Changelog, Update frequency|
|**8. Citabilidad de Formato**|8%|Tablas, Listas, Quotes, Extractabilidad|
|**9. Enlaces y Verificabilidad**|6%|Outbound links a .gov/.edu, Fuentes primarias|
|**10. Optimización Multi-Plataforma**|2%|Specificidades ChatGPT/Gemini/Perplexity|

NOTA: Los pesos han sido rebalanceados para reflejar la importancia de nuevos factores identificados en estudios recientes de citabilidad, priorizando evidencia, autoridad y estructura de respuesta.


# **4. REQUERIMIENTOS FUNCIONALES AMPLIADOS**
## **4.1. Nueva Capa de Análisis: E-E-A-T Operacional**
### **RF-NUEVO-001: Evaluación de Experience (Experiencia)**
El sistema DEBE detectar señales de experiencia de primera mano en el contenido.

- Criterios de evaluación:
- Detectar uso de primera persona con detalles específicos ("en mi experiencia con...", "cuando implementé...")
- Identificar menciones de casos específicos con datos cuantitativos
- Verificar presencia de capturas de pantalla, fotos propias, o evidencia visual de implementación
- Score: 0-100 basado en densidad de señales de experiencia práctica
### **RF-NUEVO-002: Evaluación de Expertise (Experticia)**
El sistema DEBE verificar credenciales y demostración de conocimiento profundo.

- Criterios de evaluación:
- Verificar presencia de autor con bio que incluye: credenciales académicas, certificaciones, años de experiencia
- Detectar uso de terminología técnica apropiada al nivel del tema
- Identificar referencias a metodologías, frameworks o estándares de industria
- Validar presencia de perfil de autor en Schema Person con sameAs a LinkedIn, sitio profesional, o publicaciones previas
### **RF-NUEVO-003: Evaluación de Authoritativeness (Autoridad)**
El sistema DEBE medir señales de reconocimiento externo y validación por terceros.

- Criterios de evaluación:
- Contar menciones de marca sin enlace en sitios de terceros (brand mentions)
- Verificar presencia de Schema Organization con sameAs apuntando a Wikipedia, Crunchbase, o perfiles oficiales
- Detectar citas o referencias al autor/organización en publicaciones de autoridad
- Identificar premios, reconocimientos o posiciones de liderazgo en asociaciones industriales
### **RF-NUEVO-004: Evaluación de Trustworthiness (Confiabilidad)**
El sistema DEBE verificar transparencia, verificabilidad y ausencia de señales negativas.

- Criterios de evaluación:
- Verificar presencia de página "Acerca de", "Metodología", o "Política Editorial"
- Detectar declaraciones de conflictos de interés, partnerships, o contenido patrocinado
- Validar presencia de datos de contacto reales (dirección, teléfono, email corporativo)
- Verificar HTTPS, política de privacidad, y ausencia de señales de spam
## **4.2. Sistema de Claims Governance (Gobernanza de Afirmaciones)**
### **RF-NUEVO-005: Mapeo de Claims vs Evidence**
El sistema DEBE crear un mapa de afirmaciones y sus evidencias correspondientes.

- Funcionalidad requerida:
- Extraer todas las afirmaciones fácticas del texto (statements que pueden ser verdaderos o falsos)
- Para cada afirmación, identificar si existe: enlace a fuente, cita entre comillas, referencia a estudio, o dato numérico
- Clasificar evidencias como: pública/verificable, interna/no accesible, o ausente
- Generar "Evidence Map" visual mostrando claims con/sin respaldo
- Calcular "Evidence Density Ratio": (Claims con evidencia pública / Total claims) × 100
### **RF-NUEVO-006: Detección de Fact Surface**
El sistema DEBE evaluar qué porcentaje de los claims son fact-checkeable por un tercero.

- Lógica de evaluación:
- Identificar afirmaciones con datos numéricos, fechas, nombres propios, o eventos específicos
- Verificar que cada dato venga acompañado de: (fuente + fecha de la fuente) O (enlace directo a evidencia pública)
- Penalizar afirmaciones absolutas sin matiz ("siempre", "nunca", "todos") a menos que estén respaldadas
- Score: 0-100 donde 100 = todas las afirmaciones tienen evidencia pública trazable
## **4.3. Análisis de Frescura y Changelog**
### **RF-NUEVO-007: Detección de Señales de Actualización**
El sistema DEBE identificar todas las señales que comunican frescura y mantenimiento activo.

- Elementos a detectar:
- Fecha de "Última actualización" visible en la página
- Presencia de campo dateModified en Schema Article
- Sección de "Changelog" o "Historial de actualizaciones"
- Frecuencia de actualizaciones (si hay acceso a versiones previas via Wayback Machine o similar)
- Comparación con competidores: "Freshness Lead Time" = días desde última actualización tuya vs promedio top 3 competidores
### **RF-NUEVO-008: Recomendaciones de Changelog**
El sistema DEBE generar recomendaciones específicas de actualización.

- Tipos de recomendaciones:
- Si antigüedad >90 días: "CRÍTICO: Actualizar contenido y fecha visible"
- Si faltan estadísticas recientes: "Añadir datos de [año actual] en sección X"
- Si competencia actualizada más recientemente: "Competidor Y actualizó hace Z días - priorizar refresh"
- Sugerir crear sección "/changelog" pública con bullet points de actualizaciones mayores


# **5. OPTIMIZACIÓN MULTI-PLATAFORMA: CRITERIOS ESPECÍFICOS POR LLM**
## **5.1. Empaquetado para ChatGPT (OpenAI)**
Observaciones de comportamiento:

- Prefiere pasajes auto-contenidos de 3-5 oraciones con atribución clara
- Tiende a citar fuentes que incluyen el enlace dentro de las primeras 1-2 líneas del claim
- Favorece contenido con dateModified explícito y reciente

Criterios de optimización que el sistema debe verificar:

- Párrafos de 75-150 palabras máximo después de cada H2
- Claim principal al inicio del párrafo + fuente dentro de las primeras 2 oraciones
- Timestamp visible ("Actualizado: DD/MM/YYYY") preferiblemente cerca del claim principal
- Uso de listas con bullet points para facts múltiples relacionados
## **5.2. Empaquetado para Google (Gemini + AI Overviews)**
Observaciones de comportamiento:

- Estructura Q&A y bloques FAQ se extraen limpiamente
- Schema actualizado (especialmente FAQPage y HowTo) es factor diferencial
- Prefiere respuestas de 75-150 palabras con secciones claramente delimitadas

Criterios de optimización:

- Crear bloques FAQ dedicados en páginas cornerstone
- Implementar FAQPage y HowTo schema con Question/Answer pairs
- Respuestas FAQ entre 75-150 palabras cada una
- Incluir timestamp tanto en metadata como visible al usuario
- Revisar aparición en "People Also Ask" y optimizar para esas queries exactas
## **5.3. Empaquetado para Perplexity AI**
Observaciones de comportamiento:

- Prefiere fuentes múltiples y alta densidad de source links
- Valora anchor text descriptivo en enlaces salientes
- Aparece con frecuencia en panel de "Citations" cuando hay confirmación cruzada

Criterios de optimización:

- Incluir 1-2 enlaces externos verificables por párrafo clave
- Usar anchor text muy descriptivo ("según el estudio del MIT sobre X" en vez de "este estudio")
- Priorizar enlaces a fuentes primarias (.gov, .edu, whitepapers oficiales, estudios peer-reviewed)
- Crear "Reference Section" al final del artículo con todas las fuentes citadas
## **5.4. Empaquetado para Microsoft Copilot / Bing Chat**
Observaciones de comportamiento:

- Integración fuerte con Bing Search - favorece contenido bien indexado en Bing
- Prefiere respuestas con estructura clara (listas numeradas/bullets)
- Cita frecuentemente contenido que aparece en Bing Rich Results

Criterios de optimización:

- Optimizar específicamente para Bing Webmaster Tools (puede diferir de Google)
- Usar estructura de listas y pasos numerados para procedimientos
- Implementar schema compatible con Bing Rich Results (Recipe, Product, FAQ)
## **5.5. Criterio General Multi-Plataforma**
Para maximizar citabilidad across all platforms, el sistema debe recomendar un enfoque híbrido:

1. 1. Estructura Base Universal
- Respuesta directa en primeros 150 caracteres (Power Lead)
- H2 interrogativos que mapean a preguntas reales
- Párrafos de 75-150 palabras con claim + contexto + source
1. 2. Capas de Enriquecimiento por Plataforma
- Para ChatGPT: Foco en timestamps y auto-contenido
- Para Gemini: FAQ blocks + schema robusto
- Para Perplexity: Density de external links con anchor descriptivo
- Para Copilot: Listas estructuradas + optimización Bing


# **6. SISTEMA DE AUDITORÍA Y MEDICIÓN GEO**
## **6.1. Q-Set: Conjunto de Preguntas de Referencia**
El sistema DEBE permitir al usuario definir un "Q-Set" (conjunto de 10-25 preguntas prioritarias) que representa las queries más importantes para su negocio.

- Funcionalidad requerida:
- Interfaz para añadir/editar lista de preguntas target
- Categorización por intención: informacional, navegacional, transaccional
- Priorización (alta/media/baja) para cada query
- Asignación de pregunta → página específica del sitio
## **6.2. Auditoría Mensual Multi-Plataforma**
El sistema DEBE automatizar la ejecución mensual de auditorías de citabilidad.

1. Proceso de auditoría:
- Tomar cada pregunta del Q-Set del usuario
- Ejecutar la query en: ChatGPT, Gemini, Perplexity, Copilot (vía APIs o scraping ético)
- Registrar: ¿Fuiste citado? ¿Tu fuente fue mostrada? ¿La información es precisa?
- Comparar contra mes anterior para detectar ganancias/pérdidas de share of voice
- Identificar preguntas donde competidores desplazaron tu citación

Output de la auditoría: Tabla de tracking con columnas:

|**Topic**|**Question**|**Cited?**|**Platform**|**Source Shown?**|**Accurate?**|**Next Action**|**Owner**|
| :- | :- | :- | :- | :- | :- | :- | :- |
|**GEO SaaS**|¿Qué es GEO audit?|Sí|ChatGPT|/geo-audit|Sí|Add case study|SEO Lead|
|**GEO SaaS**|¿Cómo medir GEO?|No|Gemini|-|-|Optimize H2s + FAQ|Content|
## **6.3. KPIs de Citabilidad (GEO-Specific Metrics)**
El sistema debe calcular y mostrar los siguientes KPIs:

- **Share of Voice en AI Answers**\
- Fórmula: (Queries donde apareces citado / Total queries en Q-Set) × 100\
- Target: >40%
- **Answer Coverage Rate**\
- Fórmula: (Queries contestadas con tu fuente / Total queries relevantes) × 100\
- Target: >60%
- **Citation Accuracy Rate**\
- Fórmula: (Citas que reflejan correctamente tu info / Total citas) × 100\
- Target: >95%
- **Freshness Lead Time**\
- Fórmula: Días desde tu última actualización - Promedio días desde actualización top 3 competidores\
- Target: <0 (estar más fresco que competencia)
- **Evidence Density Ratio**\
- Fórmula: (Claims con evidencia pública / Total claims) × 100\
- Target: >80%
- **E-E-A-T Composite Score**\
- Fórmula: Promedio de scores de Experience + Expertise + Authority + Trust\
- Target: >75/100


# **7. FLUJO DE TRABAJO: DE AUDITORÍA A OPTIMIZACIÓN**
## **7.1. Fase 1: Análisis Inicial (Input & Audit)**
1. Paso 1: Usuario ingresa URL o texto
1. Paso 2: Sistema ejecuta las 10 evaluaciones dimensionales
1. Paso 3: Genera Score Global (0-100) y desglose por dimensión
1. Paso 4: Crea "Evidence Map" visual de claims vs proofs
1. Paso 5: Identifica "anatomía citable" (7 elementos clave de la imagen)
1. Paso 6: Genera lista priorizada de mejoras críticas/altas/medias/bajas
## **7.2. Fase 2: Optimización Guiada (LLM-Assisted Rewrite)**
1. Paso 7: Usuario solicita optimización automática
1. Paso 8: Usuario selecciona plataforma target (ChatGPT, Gemini, Perplexity, o "Universal")
1. Paso 9: Sistema construye prompt especializado incorporando:
- Criterios de la dimensión con menor score
- Guías de empaquetado para plataforma seleccionada
- Instrucciones de Evidence Surface y E-E-A-T
1. Paso 10: LLM genera versión optimizada
1. Paso 11: Sistema re-analiza automáticamente la versión optimizada
1. Paso 12: Muestra comparación side-by-side con diferencias resaltadas
## **7.3. Fase 3: Validación y Publicación**
1. Paso 13: Usuario revisa cambios y score mejorado
1. Paso 14: Sistema genera checklist pre-publicación:
- ¿Todos los claims tienen evidencia pública verificable?
- ¿dateModified está actualizado y visible?
- ¿Schema Person/Organization incluyen sameAs con perfiles verificables?
- ¿Existe al menos un dato original o insight propietario?
- ¿H2s están formulados como preguntas reales?
- ¿Primeros 150 caracteres contienen Power Lead con entidades clave?
- ¿Hay changelog visible si es actualización?
1. Paso 15: Usuario exporta versión final (Markdown, HTML, DOCX)
1. Paso 16: Sistema añade página al Q-Set de auditoría mensual (opcional)
## **7.4. Fase 4: Monitoreo Continuo (Monthly Audit Loop)**
1. Paso 17: Sistema ejecuta auditoría mensual automática del Q-Set
1. Paso 18: Detecta pérdida de share of voice o accuracy
1. Paso 19: Genera alertas de "Content Decay" si:
- Antigüedad >90 días sin actualización
- Competencia citada con mayor frecuencia en queries del Q-Set
- Citation Accuracy cayó <90%
1. Paso 20: Recomienda refresh prioritario de páginas en declive


# **8. ESPECIFICACIONES TÉCNICAS DE IMPLEMENTACIÓN**
## **8.1. Librería NLP Requerida para E-E-A-T Detection**
Para evaluar señales de Experience, Expertise, Authority y Trust, el sistema necesitará:

- **spaCy con modelos en-core-web-lg**: Named Entity Recognition (NER) para detectar personas, organizaciones, fechas
- **NLTK Sentiment Analysis**: Detectar tono (neutral/promocional) y semantic noise
- **Regex patterns customizados**: Detectar frases de experiencia ("en mi práctica...", "después de X años...")
- **BeautifulSoup + Selenium/Playwright**: Scraping de Schema, meta tags, y contenido renderizado
- **Difflib (Python nativo)**: Comparación de versiones para changelog y content decay detection
## **8.2. Integración con APIs de Auditoría**
Para ejecutar auditorías multi-plataforma mensuales, el sistema requiere integración con:

- OpenAI API (ChatGPT): Para ejecutar queries programáticas y analizar responses
- Google Gemini API: Testing de queries y extracción de citation sources
- Anthropic API (Claude): Validación cross-platform de respuestas
- Perplexity API (si disponible): Tracking de citation panel

NOTA: Si APIs no están disponibles, implementar scraping ético con rate limiting y user-agent apropiado, respetando robots.txt de cada plataforma.
## **8.3. Base de Datos de Tracking**
El sistema debe mantener tablas para:

- **audits**: Registro histórico de cada auditoría mensual (query, platform, cited, accurate, timestamp)
- **q\_sets**: Conjuntos de preguntas por usuario/proyecto
- **evidence\_maps**: Mapeo de claims → evidence URLs por página analizada
- **content\_versions**: Historial de versiones de contenido para tracking de decay
- **competitor\_tracking**: Datos de competidores (freshness, citation frequency) para benchmarking


# **9. CRITERIOS DE ACEPTACIÓN DEL SISTEMA V2.0**
## **9.1. Funcionalidad Core Ampliada**
1. El sistema detecta correctamente los 7 elementos de "anatomía citable" en >90% de casos de prueba
1. El sistema genera Evidence Maps precisos con <5% de false positives en detección de claims
1. Los scores de E-E-A-T correlacionan con evaluación manual por expertos (R² >0.85)
1. El sistema identifica correctamente diferencias de optimización entre ChatGPT/Gemini/Perplexity
1. Las auditorías multi-plataforma completan en <5 minutos para Q-Set de 20 queries
1. El content optimizado por el sistema mejora score promedio en +25 puntos vs original
## **9.2. Precisión de Detección**
1. Power Lead detection: >95% accuracy (validado contra dataset etiquetado manualmente)
1. Claims extraction: recall >85%, precision >90%
1. Authorship detection: identifica autor + credentials en >90% de páginas que los tienen
1. Freshness signal detection: 100% accuracy para dateModified en Schema y visible text
1. External link classification (.gov/.edu/whitepaper): >95% precision
## **9.3. Usabilidad y UX**
1. Dashboard muestra "Anatomía Citable" con indicadores visuales de cumplimiento de 7 elementos
1. Evidence Map es interactiva: click en claim muestra su evidencia correspondiente
1. Gráfico de radar muestra las 10 dimensiones con código de color (rojo/amarillo/verde)
1. Comparador side-by-side resalta cambios con tooltips explicando por qué se hizo cada cambio
1. Export genera reporte PDF ejecutivo con: score, top 3 mejoras, y roadmap de acción


# **10. CONCLUSIÓN Y ROADMAP DE DESARROLLO**
Esta versión 2.0 del SRS para GEO-Auditor AI representa una evolución significativa desde la especificación original, integrando investigación actual sobre factores que determinan citabilidad en Large Language Models.
## **10.1. Diferencias Clave vs Versión 1.0**
- Expansión de 7 a 10 dimensiones de evaluación
- Incorporación de criterios de "Anatomía de Página Citable" basados en análisis visual
- Sistema completo de E-E-A-T operacional con detección automatizada
- Claims Governance y Evidence Mapping como capa crítica
- Análisis de frescura y changelog como señal de primer orden
- Optimización específica por plataforma (ChatGPT, Gemini, Perplexity, Copilot)
- Sistema de auditoría mensual con Q-Set y tracking de KPIs GEO-específicos
## **10.2. Roadmap de Implementación Sugerido**
1. **Fase 1 (Semanas 1-4): MVP con Dimensiones Core**: Infraestructura, Metadata, Estructura AEO, Densidad Evidencia, Autoridad E-E-A-T
1. **Fase 2 (Semanas 5-7): Anatomía Citable**: Detección de 7 elementos visuales, Power Lead, Claims extraction básica
1. **Fase 3 (Semanas 8-10): Evidence Mapping**: Sistema completo de Claims Governance, Fact Surface audit, Evidence Density calculation
1. **Fase 4 (Semanas 11-13): Optimización Multi-Plataforma**: Prompts especializados para ChatGPT/Gemini/Perplexity, rewrite guiado por plataforma
1. **Fase 5 (Semanas 14-16): Sistema de Auditoría**: Q-Set management, monthly audit automation, KPI dashboard con trending
1. **Fase 6 (Semanas 17-18): Testing y Refinamiento**: Validación con dataset real, calibración de pesos, UX optimization
## **10.3. Métricas de Éxito del Proyecto**
- Usuarios beta logran mejorar Citation Score promedio en +30% después de 2 ciclos de optimización
- Share of Voice en AI Answers aumenta >15 puntos porcentuales en 3 meses de uso
- Sistema identifica correctamente el 90% de oportunidades de mejora validadas por expertos SEO/GEO
- Tiempo de análisis completo <60 segundos para páginas de hasta 5000 palabras
- NPS (Net Promoter Score) del producto >50 entre early adopters


# **11. CONTROL DE VERSIONES**

|**Versión**|**Fecha**|**Autor**|**Cambios**|
| :- | :- | :- | :- |
|**1.0**|Feb 2026|Claude AI|Versión inicial con 7 dimensiones básicas|
|**2.0**|Feb 2026|Claude AI + Research|Ampliación a 10 dimensiones, E-E-A-T, Evidence Mapping, Anatomía Citable, Multi-Platform optimization|

**FIN DEL DOCUMENTO - VERSIÓN 2.0 AMPLIADA**
