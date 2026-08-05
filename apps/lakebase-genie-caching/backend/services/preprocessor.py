"""Query preprocessing: stop word removal, normalization."""

import re
import string

STOP_WORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "shall",
    "should", "may", "might", "must", "can", "could", "am", "i", "me",
    "my", "we", "our", "you", "your", "he", "she", "it", "they", "them",
    "his", "her", "its", "their", "this", "that", "these", "those",
    "what", "which", "who", "whom", "how", "when", "where", "why",
    "in", "on", "at", "to", "for", "of", "with", "by", "from", "as",
    "into", "through", "during", "before", "after", "above", "below",
    "between", "about", "against", "and", "but", "or", "nor", "not",
    "so", "if", "then", "than", "too", "very", "just", "also", "only",
    "please", "show", "tell", "give", "get", "find", "list", "display",
    "provide", "fetch", "retrieve",
})


def normalize_query(query: str) -> str:
    """Normalize a query by lowercasing, removing stop words, and cleaning whitespace."""
    text = query.lower().strip()
    text = text.translate(str.maketrans("", "", string.punctuation))
    words = text.split()
    filtered = [w for w in words if w not in STOP_WORDS]
    normalized = " ".join(filtered)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def extract_key_terms(query: str) -> list[str]:
    """Extract key terms from a query after normalization."""
    normalized = normalize_query(query)
    return normalized.split() if normalized else []
