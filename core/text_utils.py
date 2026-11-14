"""
Deterministic title and tag text-normalization helpers shared across Vault,
Steam Store resolution, and VibeEngine.
"""

import difflib
import re
from typing import Dict, Set

_ROMAN_MULTI: Dict[str, str] = {
    "ii": "2",
    "iii": "3",
    "iv": "4",
    "vi": "6",
    "vii": "7",
    "viii": "8",
    "ix": "9",
}

_ROMAN_SINGLE: Dict[str, str] = {
    "i": "1",
    "v": "5",
    "x": "10",
}


def normalize_tag_key(tag: str) -> str:
    """Normalize a tag string for punctuation/hyphen/case-insensitive matching."""
    if not tag:
        return ""
    cleaned = re.sub(r"[™®©'’`]+", "", tag.lower())
    cleaned = re.sub(r"[-_/]+", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def collapse_tag_key(tag: str) -> str:
    """Collapse whitespace/hyphens/punctuation for fuzzy-exact tag equality."""
    return re.sub(r"[^a-z0-9]+", "", (tag or "").lower())


def _expand_roman_segment(segment: str) -> str:
    """Expand Roman numerals in a single title clause while protecting leading words."""
    tokens = segment.split()
    if not tokens:
        return ""

    out = []
    last_idx = len(tokens) - 1
    for idx, tok in enumerate(tokens):
        if tok in _ROMAN_MULTI:
            out.append(_ROMAN_MULTI[tok])
        elif tok in _ROMAN_SINGLE and idx > 0 and idx == last_idx:
            # Only convert trailing single-letter numerals ('Dark Souls V', 'Final Fantasy X',
            # 'Final Fantasy I') so prefixes like 'I Am Bread', 'V Rising', 'X COM' stay intact.
            out.append(_ROMAN_SINGLE[tok])
        else:
            out.append(tok)
    return " ".join(out)


def normalize_title(title: str, convert_roman: bool = True) -> str:
    """
    Deterministically normalize a game title:
    - Strip trademark/registered/copyright symbols and apostrophes
    - Expand Roman numerals per clause ('DARK SOULS™ III' -> 'dark souls 3')
    - Normalize separators to single lowercase spaces
    """
    if not title:
        return ""

    text = title.lower()
    text = re.sub(r"[™®©]+", "", text)
    text = text.replace("’", "'").replace("‘", "'")
    text = text.replace("'", "")
    # Treat '&' as 'and' so 'Mount & Blade' / 'Mount and Blade' align cleanly
    text = re.sub(r"\s*&\s*", " and ", text)

    # Split on clause boundaries before stripping punctuation so pre-colon Roman numerals
    # like 'Sid Meier's Civilization® V: Brave New World' convert cleanly too.
    clauses = re.split(r"[:;\-–—/]+", text)
    normalized_clauses = []
    for clause in clauses:
        cleaned = re.sub(r"[^a-z0-9\s]+", " ", clause)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if not cleaned:
            continue
        if convert_roman:
            cleaned = _expand_roman_segment(cleaned)
        normalized_clauses.append(cleaned)

    return " ".join(normalized_clauses).strip()


def extract_sequel_numbers(title: str) -> Set[str]:
    """Extract numeric tokens after Roman normalization to guard sequel specificity."""
    norm = normalize_title(title, convert_roman=True)
    return set(re.findall(r"\b\d+\b", norm))


def contains_normalized_phrase(query_norm: str, candidate_norm: str) -> bool:
    """Check whether `query_norm` appears cleanly inside `candidate_norm`."""
    if not query_norm or not candidate_norm:
        return False
    if query_norm == candidate_norm:
        return True
    pattern = rf"(?:^|\b){re.escape(query_norm)}(?:\b|$)"
    if re.search(pattern, candidate_norm):
        return True
    return len(query_norm) >= 4 and query_norm in candidate_norm


def apply_sequel_digit_guard(score: float, query_nums: Set[str], candidate_nums: Set[str]) -> float:
    """
    Penalize candidates whose sequel numbering disagrees with the query:
    - Query specifies sequel digits ('Hotline Miami 2') and candidate omits them -> -0.35
    - Query omits digits ('Hotline Miami') and candidate adds sequel digits -> -0.15
    """
    if query_nums:
        if not query_nums.issubset(candidate_nums):
            return max(0.0, score - 0.35)
    elif candidate_nums:
        return max(0.0, score - 0.15)
    return score


def score_title_match(query: str, candidate: str) -> float:
    """
    Compute a normalized [0.0, 1.0] similarity score between `query` and `candidate`,
    handling trademarks, punctuation, Roman numerals, and sequel-digit precision.
    """
    q_norm = normalize_title(query, convert_roman=True)
    c_norm = normalize_title(candidate, convert_roman=True)
    if not q_norm or not c_norm:
        return 0.0
    if q_norm == c_norm:
        return 1.0

    score = difflib.SequenceMatcher(None, q_norm, c_norm).ratio()
    if contains_normalized_phrase(q_norm, c_norm):
        score = min(0.99, score + 0.12)

    q_nums = extract_sequel_numbers(query)
    c_nums = extract_sequel_numbers(candidate)
    return apply_sequel_digit_guard(score, q_nums, c_nums)
