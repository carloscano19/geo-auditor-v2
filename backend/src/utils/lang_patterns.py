"""
GEO-AUDITOR AI - Centralized Linguistic Patterns & Multi-Language Support

Centralizes language detection, regex patterns, stop words, and date/question
rules for bilingual English/Spanish analysis.
"""

import re
from datetime import datetime
from typing import Optional, Set, List, Dict, Any
import langdetect
from langdetect import DetectorFactory

# Enforce deterministic language detection
DetectorFactory.seed = 0

# Month mapping for Spanish
SPANISH_MONTH_MAP: Dict[str, int] = {
    "enero": 1, "ene": 1,
    "febrero": 2, "feb": 2,
    "marzo": 3, "mar": 3,
    "abril": 4, "abr": 4,
    "mayo": 5, "may": 5,
    "junio": 6, "jun": 6,
    "julio": 7, "jul": 7,
    "agosto": 8, "ago": 8,
    "septiembre": 9, "setiembre": 9, "sep": 9, "sept": 9, "set": 9,
    "octubre": 10, "oct": 10,
    "noviembre": 11, "nov": 11,
    "diciembre": 12, "dic": 12,
}

# Month mapping for English
ENGLISH_MONTH_MAP: Dict[str, int] = {
    "january": 1, "jan": 1,
    "february": 2, "feb": 2,
    "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "may": 5, "may": 5,
    "june": 6, "jun": 6,
    "july": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}

# English stop words for entity extraction
ENGLISH_STOP_WORDS: Set[str] = {
    "the", "a", "an", "of", "to", "in", "is", "are", "was", "were",
    "how", "what", "when", "where", "why", "which", "who", "whose", "whom",
    "for", "with", "and", "or", "guide", "review", "best", "top", "vs",
    "over", "about", "news", "more", "this", "that", "these", "those",
    "drives", "really", "just", "from", "your", "will", "can", "could",
    "does", "do", "did", "should", "would", "has", "have", "had", "been",
    "being", "be", "on", "at", "by", "its", "it", "they", "them", "their",
    "we", "us", "our", "you", "he", "him", "his", "she", "her"
}

# Spanish stop words for entity extraction
SPANISH_STOP_WORDS: Set[str] = {
    "el", "la", "los", "las", "un", "una", "unos", "unas",
    "este", "esta", "estos", "estas", "ese", "esa", "esos", "esas",
    "aquel", "aquella", "aquellos", "aquellas",
    "de", "del", "a", "al", "en", "con", "por", "para", "hacia", "desde",
    "sobre", "entre", "sin", "tras", "hasta", "según", "segun", "durante", "contra",
    "y", "e", "ni", "o", "u", "pero", "sino", "aunque", "porque", "pues",
    "es", "son", "era", "eran", "fue", "fueron", "ser", "sido", "siendo",
    "está", "esta", "están", "estan", "estaba", "estaban", "estar",
    "ha", "han", "había", "habia", "habían", "habian", "haber", "hay",
    "tiene", "tienen", "tenía", "tenia", "tenían", "tenian", "tener",
    "hace", "hacen", "hizo", "hicieron", "hacer",
    "puede", "pueden", "podía", "podia", "podían", "podian", "poder",
    "cómo", "como", "qué", "que", "cuándo", "cuando", "dónde", "donde",
    "quién", "quien", "quiénes", "quienes", "cuál", "cual", "cuáles", "cuales",
    "cuánto", "cuanto", "cuánta", "cuanta", "cuántos", "cuantos", "cuántas", "cuantas",
    "más", "mas", "menos", "muy", "mucho", "mucha", "muchos", "muchas",
    "poco", "poca", "pocos", "pocas", "todo", "toda", "todos", "todas",
    "otro", "otra", "otros", "otras", "mismo", "misma", "mismos", "mismas",
    "tan", "tanto", "tanta", "tantos", "tantas", "cada", "solo", "sólo",
    "ya", "no", "sí", "si", "también", "tambien", "además", "ademas",
    "mi", "mis", "tu", "tus", "su", "sus", "nuestro", "nuestra", "nuestros", "nuestras",
    "me", "te", "se", "nos", "os", "le", "les", "lo",
    "yo", "tú", "tu", "él", "el", "ella", "ellos", "ellas", "nosotros", "nosotras", "usted", "ustedes",
    "guía", "guia", "revisión", "revision", "mejor", "mejores", "top", "vs",
    "noticias", "noticia"
}

# Centralized patterns configuration per language
PATTERNS_BY_LANG: Dict[str, Dict[str, Any]] = {
    "en": {
        "claims": [
            r'\d+(\.\d+)?%',
            r'\b\d{1,3}(,\d{3})*\s*(million|billion|trillion|users|customers|dollars|euros|k|m|b)\b',
            r'\b(increased|decreased|grew|dropped|rose|fell|surge|plummet)(ed|s|d)?\s+by\s+\d+',
            r'\b(studies|research|reports|surveys?|data)\s+(shows?|indicate[sd]?|proves?|suggests?|demonstrates?|found)\b',
            r'\baccording\s+to\s+\w+',
            r'\bas\s+stated\s+by\s+\w+',
            r'\bbased\s+on\s+(a\s+)?(study|report|survey|data|research)\b',
            r'[\$£€]\s*\d+([.,]\d+)?\s*(million|billion|trillion|k|m|b)?\b',
            r'\b\d{4}\s+(study|report|survey|census)\b',
        ],
        "authorship": [
            r"\b(?i:written\s+by)\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+)+",
            r"\b(?i:author:)\s*[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+)+",
            r"\b(?i:by)\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+)+",
            r"\b(?i:reviewed\s+by)\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+)+",
            r"\b(?i:fact\s+checked\s+by)\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+)+",
            r"\b(?i:published\s+by)\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+)+",
            r"\b(?i:edited\s+by)\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+)+",
        ],
        "experience": [
            r"(?i)\b(?:i|we)\s+(?:tested|analyzed|found|discovered|observed|evaluated|reviewed|verified|measured|built|conducted)\b",
            r"(?i)\bin\s+(?:my|our)\s+(?:experience|opinion|view|analysis|testing|tests?|experiments?|research)\b",
            r"(?i)\b(?:i|we)\s+(?:have\s+)?(?:used|tried|spent)\b",
            r"(?i)\b(?:i|we)\s+personally\b",
            r"(?i)\bhands?-on\s+(?:test|review|experience)\b",
            r"(?i)\bour\s+(?:findings|analysis|results|team)\b",
        ],
        "stop_words": ENGLISH_STOP_WORDS,
        "declarative_verbs_regex": (
            r'\b(is|are|was|were|means|refers to|defined as|consists of|'
            r'offers|provides|allows|announces|launches|reveals|demonstrates|shows)\b'
        ),
        "logical_connectors": [
            'therefore', 'however', 'because', 'thus', 'consequently',
            'furthermore', 'in contrast', 'for example', 'as a result', 'since',
            'moreover', 'in addition', 'specifically', 'similarly', 'nevertheless', 'accordingly'
        ],
        "generic_headers": [
            'introduction', 'conclusion', 'summary', 'overview',
            'final thoughts', 'background', 'the basics', 'about', 'details', 'general', 'more info'
        ],
        "visual_date_patterns": [
            r'(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}',
            r'\b\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}\b',
            r'\b\d{1,2}/\d{1,2}/\d{4}\b',
            r'(?:updated|published|posted)\s*(?:on)?\s*:?\s*(\d{4}-\d{2}-\d{2})'
        ],
        "month_map": ENGLISH_MONTH_MAP,
        "methodology_signals": [
            r'\bmethodology\b',
            r'\bsample\s+of\b',
            r'\bwe\s+analyzed\b',
            r'\bour\s+data\b',
            r'\bthis\s+study\b',
            r'\bwe\s+surveyed\b',
            r'\bour\s+(?:research|survey|benchmark|dataset)\b',
            r'\bwe\s+measured\b',
            r'\bwe\s+collected\b',
            r'\blimitations\s+of\s+this\s+study\b',
            r'\bhow\s+we\s+did\s+this\b',
        ],
        "first_party_claims": [
            r'\b(?:we|i)\s+(?:found|analyzed|observed|discovered|measured|tested|calculated)\b',
            r'\b(?:our|my)\s+(?:data|study|research|findings|analysis|results|survey|benchmark)\s+(?:shows?|indicate[sd]?|demonstrates?|found|proves?|suggests?)\b',
            r'\bin\s+(?:our|my)\s+(?:tests?|experiments?|analysis|testing|research|study)\b',
            r'\bwe\s+collected\b',
        ],
        "referential_starters": [
            r'^\s*(?:as\s+mentioned\s+(?:above|earlier|previously)|as\s+(?:we\s+have\s+)?seen|as\s+discussed|as\s+stated\s+(?:above|earlier))\b',
            r'^\s*(?:this|these|those|such|the\s+above)\b',
            r'^\s*(?:it|they)\s+(?:is|are|was|were|has|have|can|will|also)\b',
            r'^\s*(?:as\s+noted|as\s+described|in\s+addition\s+to\s+the\s+above)\b',
        ],
    },
    "es": {
        "claims": [
            r'\d+(\.\d+)?%',
            r'\b\d+([.,]\d+)?\s*(por\s+ciento|porcentaje)\b',
            r'\b\d{1,3}([.,]\d{3})*\s*(millones?|mil\s+millones?|billones?|usuarios?|clientes?|d[oó]lares|euros|k|m|b)\b',
            r'\b(aument[oó]|creci[oó]|cay[oó]|disminuy[oó]|subi[oó]|baj[oó]|se\s+increment[oó]|se\s+redujo)\s+(un|en\s+un)?\s*\d+',
            r'\b(los\s+)?(estudios?|investigaciones|informes?|reportes?|encuestas?|datos?)\s+(muestran?|indican?|demuestran?|revelan?|sugieren?|encontraron?)\b',
            r'\b(según|segun|de\s+acuerdo\s+con)\b',
            r'\bun\s+estudio\s+de\b',
            r'\b(basado|basada|basados|basadas)\s+en\s+(un\s+|el\s+|los\s+|las\s+)?(estudio|informe|reporte|encuesta|investigaci[oó]n|datos?)\b',
            r'[\$€]\s*\d+([.,]\d+)?\s*(millones?|mil\s+millones?|billones?|k|m|b)?\b',
            r'\b\d+([.,]\d+)?\s*(euros?|d[oó]lares?)\b',
            r'\b(estudio|informe|encuesta)\s+de\s+\d{4}\b',
        ],
        "authorship": [
            r"\b(?i:escrito\s+por)\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+)+",
            r"\b(?i:autor:)\s*[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+)+",
            r"\b(?i:por)\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+)+",
            r"\b(?i:revisado\s+por)\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+)+",
            r"\b(?i:publicado\s+por)\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+)+",
            r"\b(?i:editado\s+por)\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+)+",
            r"\b(?i:verificado\s+por)\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+)+",
        ],
        "experience": [
            r"(?i)\b(?:hemos|he)\s+(?:probado|evaluado|medido|observado|analizado|comprobado|investigado|revisado|verificado|utilizado|usado)\b",
            r"(?i)\b(?:probamos|evaluamos|medimos|observamos|analizamos|comprobamos|investigamos|verificamos)\b",
            r"(?i)\ben\s+(?:nuestra|mi)\s+(?:experiencia|opini[oó]n|visi[oó]n|an[aá]lisis|pruebas?|experimentos?|investigaci[oó]n)\b",
            r"(?i)\b(?:encontramos|descubrimos|hallamos)\s+que\b",
            r"(?i)\b(?:nuestros|nuestras|mis)\s+(?:hallazgos|resultados|conclusiones|an[aá]lisis|equipo)\b",
            r"(?i)\b(?:de\s+primera\s+mano|personalmente)\b",
        ],
        "stop_words": SPANISH_STOP_WORDS,
        "declarative_verbs_regex": (
            r'\b(es|son|era|eran|fue|ofrece|ofrecen|permite|permiten|cuenta\s+con|brinda|brindan|'
            r'se\s+refiere\s+a|representa|representan|significa|significan|consiste\s+en|'
            r'se\s+define\s+como|anuncia|presenta|demuestra|muestra)\b'
        ),
        "logical_connectors": [
            'por tanto', 'por lo tanto', 'sin embargo', 'porque', 'además', 'ademas',
            'por consiguiente', 'en consecuencia', 'como resultado', 'por otro lado',
            'en contraste', 'específicamente', 'especificamente', 'por ejemplo',
            'de manera similar', 'no obstante', 'así pues', 'asi pues', 'ya que', 'dado que'
        ],
        "generic_headers": [
            'introducción', 'introduccion', 'conclusión', 'conclusion', 'resumen', 'general',
            'antecedentes', 'detalles', 'más información', 'mas informacion', 'acerca de',
            'sobre nosotros', 'aspectos básicos', 'aspectos basicos', 'pensamientos finales'
        ],
        "visual_date_patterns": [
            r'(?:actualizado|publicado|última\s+modificación|ultima\s+modificacion|revisado)\s*(?:el|en)?\s*:?\s*(\d{1,2}\s+de\s+[a-záéíóúñ]+\s+(?:de\s+|del\s+)?\d{4})',
            r'\b(\d{1,2}\s+de\s+[a-záéíóúñ]+\s+(?:de\s+|del\s+)?\d{4})\b',
            r'\b\d{1,2}/\d{1,2}/\d{4}\b',
            r'(?:actualizado|publicado|posteado)\s*(?:el)?\s*:?\s*(\d{4}-\d{2}-\d{2})'
        ],
        "month_map": SPANISH_MONTH_MAP,
        "methodology_signals": [
            r'\bmetodolog[ií]a\b',
            r'\bmuestra\s+de\b',
            r'\bhe\s+analizado\b',
            r'\bhemos\s+analizado\b',
            r'\banalizamos\b',
            r'\beste\s+estudio\b',
            r'\bnuestros\s+datos\b',
            r'\bnuestra\s+(?:investigaci[oó]n|encuesta)\b',
            r'\bhe\s+medido\b',
            r'\bhe\s+descargado\b',
            r'\bhe\s+recogido\b',
            r'\bhe\s+lanzado\s+un\s+estudio\b',
            r'\bestudio\s+express\b',
            r'\bmini-estudio\b',
            r'\bl[ií]mites\s+de\s+este\s+estudio\b',
            r'\ben\s+qu[eé]\s+consiste\s+este\s+an[aá]lisis\b',
        ],
        "first_party_claims": [
            r'\b(?:encontramos|descubrimos|observamos|medimos|probamos|hallamos|calculamos)\b',
            r'\b(?:hemos|he)\s+(?:encontrado|analizado|observado|medido|probado|descubierto)\b',
            r'\b(?:nuestros|mis)\s+(?:datos|hallazgos|resultados|an[aá]lisis)\s+(?:muestran?|indican?|demuestran?|revelan?)\b',
            r'\b(?:nuestro|mi)\s+(?:estudio|informe|reporte|experimento)\s+(?:muestra|indica|demuestra|revela)\b',
            r'\ben\s+(?:nuestras|mis)\s+pruebas\b',
        ],
        "referential_starters": [
            r'^\s*(?:como\s+(?:hemos|se\s+ha)\s+visto|como\s+se\s+mencion[oó]|como\s+dec[ií]amos|como\s+se\s+dijo|como\s+vimos)\b',
            r'^\s*(?:esto|estos|estas|lo\s+anterior|dicho\s+esto)\b',
            r'^\s*(?:dichos?|dichas?)\b',
            r'^\s*(?:como\s+se\s+ha\s+explicado|tal\s+como\s+vimos)\b',
        ],
    }
}

INTERROGATIVE_WORDS: Set[str] = {
    'what', 'why', 'how', 'when', 'where', 'who', 'which', 'whose', 'whom',
    'can', 'could', 'is', 'are', 'do', 'does', 'did', 'should', 'would', 'will',
    'qué', 'que', 'cómo', 'como', 'cuándo', 'cuando', 'dónde', 'donde',
    'cuál', 'cual', 'cuáles', 'cuales', 'quién', 'quien', 'quiénes', 'quienes',
    'cuánto', 'cuanto', 'cuánta', 'cuanta', 'cuántos', 'cuantos', 'cuántas', 'cuantas',
    'puede', 'pueden'
}

INTERROGATIVE_PREFIXES = (
    'por qué', 'por que', 'para qué', 'para que',
    'de qué', 'de que', 'a qué', 'a que'
)

# Explanatory H1 patterns for distinguishing educational/guide content from pure news
EXPLANATORY_H1_STARTERS_EN = (
    r'\bwhat\s+(?:is|are)\b',
    r'\bhow\s+to\b',
    r'\bhow\s+(?:does|do)\b',
    r'\bwhy\b',
    r'\bguide\b',
    r'\bdifferences\s+between\b',
)

EXPLANATORY_H1_STARTERS_ES = (
    r'\bqu[eé]\s+(?:es|son)\b',
    r'\bc[oó]mo\b',
    r'\bpor\s+qu[eé]\b',
    r'\bgu[ií]a\b',
    r'\bdiferencias\s+entre\b',
)

EXPLANATORY_H1_STRUCTURES = (
    r'\bvs\.?\b',
    r'\bdifferences\s+between\b',
    r'\bdiferencias\s+entre\b',
)


def is_explanatory_h1(text: str) -> bool:
    """
    Determine if an H1 header represents explanatory/guide content rather than pure news.
    Checks for English and Spanish patterns at the beginning of the H1 or clear structural markers:
    EN: "what is/are", "how to", "how does/do", "why", "guide", "differences between", " vs "
    ES: "qué es/son", "cómo", "por qué", "guía", "diferencias entre"
    """
    if not text:
        return False
    t = text.strip().lower()
    # Strip opening punctuation, inverted question marks, quotes
    cleaned = re.sub(r'^[^\w¿"\'`]+', '', t)
    cleaned = re.sub(r'^[¿"\'`]+', '', cleaned).strip()

    # 1. Structural markers anywhere in the H1
    for pattern in EXPLANATORY_H1_STRUCTURES:
        if re.search(pattern, cleaned, re.IGNORECASE):
            return True

    # 2. Starters at the beginning of the H1
    for pattern in EXPLANATORY_H1_STARTERS_EN + EXPLANATORY_H1_STARTERS_ES:
        if re.match(r'^\s*' + pattern, cleaned, re.IGNORECASE):
            return True

    return False


def detect_language(text: str) -> str:
    """
    Detect language of content using langdetect.
    Returns 'es' if detected as Spanish, otherwise 'en'.
    Fallback to 'en' on short text, error, or ambiguity.
    """
    if not text or len(text.strip()) < 10:
        return "en"
    try:
        lang = langdetect.detect(text)
        return "es" if lang == "es" else "en"
    except Exception:
        return "en"


def get_lang_patterns(lang: str = "en") -> Dict[str, Any]:
    """Get pattern dictionary for given language code ('en' or 'es')."""
    normalized = "es" if lang and lang.lower().startswith("es") else "en"
    return PATTERNS_BY_LANG[normalized]


def is_interrogative_h2(text: str) -> bool:
    """
    Determine if an H2 header is question-formatted.
    Considers questions that end in '?', start with '¿', or start with an
    interrogative word/phrase in English or Spanish.
    """
    if not text:
        return False
    t = text.strip()
    if t.endswith('?') or t.startswith('¿'):
        return True
    
    # Strip non-word characters from the beginning
    cleaned = re.sub(r'^[^\w¿]+', '', t).lower()
    
    # Check multi-word interrogative prefixes
    for prefix in INTERROGATIVE_PREFIXES:
        if cleaned.startswith(prefix + ' ') or cleaned == prefix:
            return True
            
    # Check single-word interrogatives
    words = re.findall(r'\b[\wáéíóúüñ]+\b', cleaned)
    if words and words[0] in INTERROGATIVE_WORDS:
        return True
        
    return False


def parse_date_string(date_str: str, lang: str = "en") -> Optional[datetime]:
    """
    Parse date from string with robust English and Spanish pattern support.
    """
    if not date_str:
        return None
    cleaned = date_str.strip()
    
    # 1. Spanish format: "24 de septiembre de 2026" or "24 de septiembre del 2026"
    m_es = re.search(r'\b(\d{1,2})\s+de\s+([a-záéíóúñ]+)(?:\s+(?:de|del|,))?\s+(\d{4})\b', cleaned, re.IGNORECASE)
    if m_es:
        day = int(m_es.group(1))
        month_str = m_es.group(2).lower()
        year = int(m_es.group(3))
        if month_str in SPANISH_MONTH_MAP:
            try:
                return datetime(year, SPANISH_MONTH_MAP[month_str], day)
            except ValueError:
                pass
                
    # 2. English format: "September 24, 2026"
    m_en = re.search(r'\b([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})\b', cleaned, re.IGNORECASE)
    if m_en:
        month_str = m_en.group(1).lower()
        day = int(m_en.group(2))
        year = int(m_en.group(3))
        if month_str in ENGLISH_MONTH_MAP:
            try:
                return datetime(year, ENGLISH_MONTH_MAP[month_str], day)
            except ValueError:
                pass

    # 3. English format: "24 September 2026"
    m_en2 = re.search(r'\b(\d{1,2})\s+([A-Za-z]+),?\s+(\d{4})\b', cleaned, re.IGNORECASE)
    if m_en2:
        day = int(m_en2.group(1))
        month_str = m_en2.group(2).lower()
        year = int(m_en2.group(3))
        if month_str in ENGLISH_MONTH_MAP:
            try:
                return datetime(year, ENGLISH_MONTH_MAP[month_str], day)
            except ValueError:
                pass

    # 4. Standard ISO and numeric date formats
    formats = [
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%d/%m/%Y",
        "%m/%d/%Y",
    ]
    for fmt in formats:
        try:
            tmp = cleaned
            if tmp.endswith('Z'):
                tmp = tmp[:-1]
            if '.' in tmp and 'T' in tmp:
                tmp = tmp.split('.')[0]
            return datetime.strptime(tmp, fmt)
        except ValueError:
            continue
            
    return None


def resolve_language(page_data: Any) -> str:
    """
    Resolve language from PageData object.
    If explicitly set and not empty, returns it.
    Otherwise detects from page_data.text_content.
    """
    lang = getattr(page_data, "language", None)
    if lang and lang != "en":
        return lang
    text = getattr(page_data, "text_content", "")
    if text:
        return detect_language(text)
    return "en"


# ---------------------------------------------------------------------------
# Press Release Dateline Patterns (EN and ES)
# ---------------------------------------------------------------------------

_PRESS_MONTHS_EN = (
    r"(?i:January|February|March|April|May|June|July|August|September|October|November|December|"
    r"Jan\.?|Feb\.?|Mar\.?|Apr\.?|Jun\.?|Jul\.?|Aug\.?|Sep\.?|Sept\.?|Oct\.?|Nov\.?|Dec\.?)"
)

_PRESS_MONTHS_ES = (
    r"(?i:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre|"
    r"ene\.?|feb\.?|mar\.?|abr\.?|may\.?|jun\.?|jul\.?|ago\.?|sep\.?|sept\.?|set\.?|oct\.?|nov\.?|dic\.?)"
)

# Date formats:
# EN: "September 2nd, 2026", "September 2, 2026", "Sept. 2, 2026", "2 September 2026"
_PRESS_DATE_EN = rf"(?:{_PRESS_MONTHS_EN}\s+\d{{1,2}}(?:st|nd|rd|th)?(?:,)?\s+\d{{4}}|\d{{1,2}}(?:st|nd|rd|th)?\s+{_PRESS_MONTHS_EN}\s+\d{{4}})"

# ES: "2 de septiembre de 2026", "2 de septiembre del 2026", "septiembre 2, 2026"
_PRESS_DATE_ES = rf"(?:\d{{1,2}}(?:st|nd|rd|th)?\s+(?i:de\s+)?{_PRESS_MONTHS_ES}(?:\s+(?i:de|del)|,)?\s+\d{{4}}|{_PRESS_MONTHS_ES}\s+\d{{1,2}}(?:,)?\s+\d{{4}})"

_PRESS_DATE = rf"(?:{_PRESS_DATE_EN}|{_PRESS_DATE_ES})"

# Wire services: (Business Wire), /PRNewswire/, Business Wire, PRNewswire
_PRESS_WIRE = r"(?i:\((?:Business\s*Wire|PR\s*Newswire)\)|/(?:PRNewswire|BusinessWire)/|Business\s*Wire|PRNewswire)"

# 1. Uppercase location: one or more uppercase words; connectors and/y/& in lower or upper
_PRESS_UPPER_WORD = r"[A-ZÁÉÍÓÚÑ]{2,}"
_PRESS_UPPER_LOCATION = rf"{_PRESS_UPPER_WORD}(?:\s+(?:[A-ZÁÉÍÓÚÑ]{{2,}}|(?i:and|y|&)))*"
_PRESS_DASH_ANY = r"(?:[\u2014\u2013\-]{1,2})"
_PRESS_DASH_EM_EN = r"[\u2014\u2013]"

# Separator between date and body:
# Allows optional ":" or "." (with optional whitespace) before the dash in both variants.
# In uppercase variant, also accepts ":" alone as separator.
_PRESS_SEP_UPPER = rf"(?:\s*(?:[:\.]\s*)?{_PRESS_DASH_ANY}|\s*:)"
_PRESS_SEP_CAP = rf"(?:\s*(?:[:\.]\s*)?{_PRESS_DASH_EM_EN})"

DATELINE_UPPER_REGEX = re.compile(
    rf"\b({_PRESS_UPPER_LOCATION})\s*,\s*(?:{_PRESS_WIRE}\s*,\s*)?({_PRESS_DATE})\s*(?:{_PRESS_WIRE}\s*)?{_PRESS_SEP_UPPER}"
)

# 2. Capitalized location: 1 capitalized word or 2 joined by and/y/&; dash MUST be em-dash or en-dash
_PRESS_CAP_WORD = r"[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+"
_PRESS_CAP_LOCATION = rf"{_PRESS_CAP_WORD}(?:\s+(?:and|y|&)\s+{_PRESS_CAP_WORD})?"

DATELINE_CAP_REGEX = re.compile(
    rf"\b({_PRESS_CAP_LOCATION})\s*,\s*(?:{_PRESS_WIRE}\s*,\s*)?({_PRESS_DATE})\s*(?:{_PRESS_WIRE}\s*)?{_PRESS_SEP_CAP}"
)

# 3. Following rejection: min read, minute read, minutes, min de lectura, minutos, comments, comentarios within 40 chars
FOLLOWING_REJECT_REGEX = re.compile(
    r"\b(min\s+read|minute\s+read|minutes|min\s+de\s+lectura|minutos|comments|comentarios)\b",
    re.IGNORECASE
)

# 4. Preceding rejection: By, Por, Posted by, Publicado por, Updated, Actualizado, Written by, Escrito por
PRECEDING_REJECT_REGEX = re.compile(
    r"\b(by|por|posted\s+by|publicado\s+por|updated|actualizado|written\s+by|escrito\s+por)\b[\s:]*$",
    re.IGNORECASE
)

BLOCKED_LOCATIONS = {"UPDATED", "ACTUALIZADO", "ACTUALIZADA", "UPDATE", "BY", "POR", "POSTED", "PUBLICADO"}

SENTENCE_BOUNDARY_REGEX = re.compile(r"[\.\!\?\:\n]\s*$")
PRECEDING_CAP_WORD_REGEX = re.compile(r"[A-ZÁÉÍÓÚÑ][a-záéíóúñA-ZÁÉÍÓÚÑ]*\s*$")

# 5. Wire equivalent signal
WIRE_EQUIVALENT_REGEX = re.compile(
    r"\((?:Business\s*Wire|PR\s*Newswire)\)|/(?:PRNewswire|BusinessWire)/",
    re.IGNORECASE
)


def is_press_release_dateline(text: str) -> bool:
    """
    Detect if the given text begins with or contains a press release dateline
    within the first 400 characters.
    
    Checks for:
    - ALL-UPPERCASE location(s) followed by comma, date (EN/ES), and any dash.
    - Capitalized location(s) (1 word or 2 joined by and/y/&) followed by comma,
      date (EN/ES), and an em-dash (—) or en-dash (–) (never a normal hyphen).
    - Wire service markers such as (Business Wire) or /PRNewswire/.
    - Rejects matches preceded by author/date prefixes (By, Updated, etc.)
      or followed within 40 characters by reading-time/comment metadata.
    """
    if not text:
        return False
    snippet = text[:400]

    # Check standalone agency wire signals first
    if WIRE_EQUIVALENT_REGEX.search(snippet):
        return True

    for regex in (DATELINE_UPPER_REGEX, DATELINE_CAP_REGEX):
        for m in regex.finditer(snippet):
            loc = m.group(1).strip()
            if loc.upper() in BLOCKED_LOCATIONS:
                continue

            preceding = snippet[:m.start()]

            # Specific constraints for capitalized location datelines (DATELINE_CAP_REGEX only):
            if regex is DATELINE_CAP_REGEX:
                # Must be at start of snippet or immediately after a sentence boundary (. ! ? : or newline)
                if preceding.strip() and not SENTENCE_BOUNDARY_REGEX.search(preceding):
                    continue
                # Reject if immediately preceded by a capitalized word (e.g. author first name)
                if PRECEDING_CAP_WORD_REGEX.search(preceding):
                    continue

            # Check preceding text for author/update prefixes
            if PRECEDING_REJECT_REGEX.search(preceding):
                continue

            # Check following text (next 40 chars) for reading time / comments metadata
            following = snippet[m.end():m.end() + 40]
            if FOLLOWING_REJECT_REGEX.search(following):
                continue

            return True

    return False


# Editorial verification instructions to filter from AI-generated paragraphs
VERIFICATION_EDITORIAL_PHRASES: Dict[str, List[str]] = {
    "en": [
        "should be verified",
        "should be checked",
        "needs to be verified",
        "must be verified",
    ],
    "es": [
        "debería verificarse",
        "deberia verificarse",
        "habría que comprobar",
        "habria que comprobar",
    ],
}

# Financial/investment advice phrases prohibited in AI-generated answers and paragraphs
FINANCIAL_ADVICE_PHRASES: Dict[str, List[str]] = {
    "en": [
        "investors should",
        "you should invest",
        "consider investing",
    ],
    "es": [
        "los inversores deberían",
        "los inversores deberian",
        "deberías invertir",
        "deberias invertir",
    ],
}

# Technical suggestions prohibited in data_opportunities (must be factual/content only)
TECHNICAL_DATA_OPP_PHRASES: Dict[str, List[str]] = {
    "en": [
        "schema",
        "structured data",
        "alt text",
        "metadata",
    ],
    "es": [
        "schema",
        "datos estructurados",
        "alt text",
        "metadatos",
        "metadata",
    ],
}

# Phrases indicating that draft answer acknowledges page lacks info (must reclassify to needs_info)
MISSING_INFO_ANSWER_PHRASES: Dict[str, List[str]] = {
    "en": [
        "does not name",
        "does not provide",
        "does not specify",
        "not specified",
    ],
    "es": [
        "no menciona",
        "no indica",
    ],
}

# Forbidden keywords in questions_to_answer (financial/stock/revenue queries)
DISCARD_QUESTION_KEYWORDS: Dict[str, List[str]] = {
    "en": [
        "stock price",
        "share price",
        "revenue",
        "returns",
        "should i invest",
    ],
    "es": [
        "precio de la acción",
        "precio de la accion",
        "cotización",
        "cotizacion",
        "ingresos",
        "rentabilidad",
    ],
}


def _format_score_number(val: Any) -> str:
    """Format numeric score (e.g. 50.0 -> '50', 52.5 -> '52.5')."""
    if val is None:
        return ""
    try:
        f = float(val)
        if f.is_integer():
            return str(int(f))
        return f"{f:.1f}".rstrip("0").rstrip(".")
    except Exception:
        return str(val)


def generate_ahrefs_recommendations(
    referring_domains: Optional[int] = None,
    organic_keywords: Optional[int] = None,
    top3_keywords: Optional[int] = None,
    url_rating: Optional[float] = None,
    domain_rating: Optional[float] = None,
    language: str = "en",
    linking_pages: Optional[List[Any]] = None,
) -> List[str]:
    """
    Generate deterministic rule-based recommendations from Ahrefs off-page signals.
    Bilingual support (English default, Spanish if language starts with 'es').
    Rules without available data are skipped.
    """
    lang = "es" if str(language).lower().startswith("es") else "en"
    recs: List[str] = []

    # Rule 1 & 2: Referring domains
    if referring_domains is not None:
        if referring_domains == 0:
            if lang == "es":
                recs.append(
                    "Ningún otro sitio web enlaza a esta página. Los motores de IA se basan en páginas que otros referencian: promociónala (colaboradores, notas de prensa, enlaces internos desde tus páginas más fuertes)."
                )
            else:
                recs.append(
                    "No other website links to this page. AI engines rely on pages that others reference: promote it (partners, PR, internal links from your strongest pages)."
                )
        elif 1 <= referring_domains <= 4:
            if lang == "es":
                recs.append(
                    f"Solo {referring_domains} sitios web enlazan a esta página. Conseguir algunos enlaces más de sitios relevantes reforzaría su autoridad."
                )
            else:
                recs.append(
                    f"Only {referring_domains} websites link to this page. Earning a few more links from relevant sites would strengthen its authority."
                )

    # Rule 3 & 4: Keywords & Rankings
    if organic_keywords is not None:
        if organic_keywords == 0:
            if lang == "es":
                recs.append(
                    "Esta página no posiciona en el top 100 de Google para ninguna palabra clave. Los motores de IA citan principalmente páginas que ya posicionan; mejora primero el contenido en la página y apunta a una consulta de búsqueda clara."
                )
            else:
                recs.append(
                    "This page doesn't rank in Google's top 100 for any keyword. AI engines mostly cite pages that already rank; improve on-page content first and target a clear search query."
                )
        elif organic_keywords > 0 and top3_keywords is not None and top3_keywords == 0:
            if lang == "es":
                recs.append(
                    f"La página posiciona para {organic_keywords} palabras clave pero ninguna en el top 3. Reforzar el contenido para su consulta principal es la forma más rápida de ser citado."
                )
            else:
                recs.append(
                    f"The page ranks for {organic_keywords} keywords but none in the top 3. Strengthening the content for its main query is the fastest way to get cited."
                )

    # Rule 5: Low UR with strong DR
    if url_rating is not None and domain_rating is not None:
        if url_rating < 10.0 and domain_rating >= 50.0:
            dr_str = _format_score_number(domain_rating)
            ur_str = _format_score_number(url_rating)
            if lang == "es":
                recs.append(
                    f"El dominio es fuerte (DR {dr_str}) pero esta página tiene poca autoridad propia (UR {ur_str}). Enlázala desde tus páginas más visitadas."
                )
            else:
                recs.append(
                    f"The domain is strong (DR {dr_str}) but this page has little authority of its own (UR {ur_str}). Link to it from your most visited pages."
                )

    # Rule 6: Low authority / spam backlinks
    if linking_pages:
        valid_items = [p for p in linking_pages if p is not None]
        if valid_items:
            def _is_low_auth_or_spam(p: Any) -> bool:
                is_sp = getattr(p, "spam", None) if not isinstance(p, dict) else p.get("spam")
                if is_sp is True:
                    return True
                dr = getattr(p, "domain_rating", None) if not isinstance(p, dict) else p.get("domain_rating")
                if dr is not None:
                    try:
                        return float(dr) < 10.0
                    except (ValueError, TypeError):
                        pass
                return False

            low_auth_count = sum(1 for p in valid_items if _is_low_auth_or_spam(p))
            if low_auth_count > len(valid_items) / 2:
                if lang == "es":
                    recs.append(
                        "La mayoría de los sitios que enlazan a esta página tienen poca autoridad. Céntrate en conseguir enlaces de sitios relevantes y consolidados."
                    )
                else:
                    recs.append(
                        "Most sites linking to this page have little authority. Focus on earning links from relevant, established sites."
                    )

    return recs


def strip_page_meta_references(text: str) -> str:
    """
    Remove sentences that refer to 'the page', 'this page', 'the page's',
    'la página', or 'esta página' from final publishable web copy.
    """
    if not text:
        return ""
    # Split by sentence end punctuation followed by whitespace (or end of string)
    raw_sentences = re.split(r"(?<=[.!?])\s+", text.strip())

    forbidden_pattern = re.compile(
        r"\b(the\s+page('s)?|this\s+page|la\s+p[aá]gina|esta\s+p[aá]gina)\b",
        re.IGNORECASE
    )

    kept = []
    for s in raw_sentences:
        s_clean = s.strip()
        if not s_clean:
            continue
        if forbidden_pattern.search(s_clean):
            continue
        kept.append(s_clean)

    return " ".join(kept).strip()



