import re

# Questions about the whole collection ("overview", "what topics does the book cover") are poor fits for
# top-k chunk search: no 3 chunks can represent a book. They are better answered from community summaries.
# A transparent keyword heuristic is used on purpose: it costs no LLM call and is easy to audit and extend.
_BROAD_PATTERNS = [
    r"\b(overview|summar(y|ise|ize|ising|izing)|big picture|outline)\b",
    r"\b(main|key|major|central|core|primary)\s+(topics?|themes?|ideas?|points?|concepts?|takeaways?|subjects?|areas?)\b",
    r"\bwhat\s+(is|are)\s+(this|the|these|my|those)\s+(book|document|documents|paper|papers|notes|collection|files?|material)(\s+of\s+\w+)?\s+(about|cover|covers|contain|contains)\b",
    r"\bwhat\s+(topics?|themes?|subjects?|areas?|kinds?|types?|sorts?)\b.*\b(cover|covers|covered|discuss|discusses|discussed|describe|describes|described|include|includes|included|explain|explains|explained|contain|contains)\b",
    r"\b(techniques|methods|algorithms|approaches|concepts|topics|models)\b.*\b(covered|described|discussed|presented|explained|mentioned)\b",
    r"\b(techniques|methods|algorithms|approaches|concepts|topics)\b.*\b(does|do)\s+(the|this|my)\s+(book|document|paper|notes|material)\b",
    r"\bacross\s+(all\s+)?(of\s+)?(my|the)\s+(documents|notes|papers|books|files)\b",
    r"\blist\s+(all|the\s+main|the\s+key|every)\b",
]
_BROAD = [re.compile(p, re.IGNORECASE) for p in _BROAD_PATTERNS]
# "Summarise chapter 2" is about one section, which chunk search handles better than collection-level summaries.
_SPECIFIC = re.compile(r"\b(chapter|section|page|figure|table|listing)\s+[a-z]?\d+", re.IGNORECASE)


def is_broad_query(query: str) -> bool:
    return not _SPECIFIC.search(query) and any(p.search(query) for p in _BROAD)
