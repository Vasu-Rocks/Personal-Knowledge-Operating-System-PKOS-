import re
import unicodedata

# Canonical relationship vocabulary. New extractions are constrained to it (JSON-schema enum) and every
# predicate is normalised through PREDICATE_MAP, so 'USED_BY', 'IS_USED_BY', 'USED_IN' ... stop being 5 edge types.
PREDICATES = [
    "USES", "USED_FOR", "CONTAINS", "IS_A", "DEFINES", "HAS", "CAUSES", "BUILT_ON",
    "PRODUCES", "REQUIRES", "PROVIDES", "IMPLEMENTS", "PREDICTS", "DIFFERS_FROM", "APPLIES_TO", "RELATED_TO",
]

# raw predicate -> (canonical predicate, swap source and target)
PREDICATE_MAP: dict[str, tuple[str, bool]] = {}


def _add(canonical: str, raw: list[str], flip: bool = False):
    for r in raw:
        PREDICATE_MAP[r] = (canonical, flip)


_add("USES", ["USES", "USE", "USING", "UTILIZES", "EMPLOYS"])
_add("USES", ["USED_BY", "IS_USED_BY"], flip=True)
_add("USED_FOR", ["USED_FOR", "IS_USED_FOR", "USED_IN", "IS_USED_IN", "USED_ON", "USED_TO", "USED", "IS_USED_TO", "USEFUL_FOR"])
_add("CONTAINS", ["CONTAINS", "INCLUDES", "CONSISTS_OF", "COMPRISES", "HAS_PART"])
_add("CONTAINS", ["PART_OF", "IS_PART_OF", "IS_INCLUDED_IN", "BELONGS_TO", "IS_CONTAINED_IN"], flip=True)
_add("IS_A", ["IS_A", "IS", "IS_TYPE_OF", "IS_A_TYPE_OF", "TYPE_OF", "IS_AN", "IS_A_KIND_OF", "IS_A_FORM_OF", "INSTANCE_OF", "IS_AN_INSTANCE_OF"])
_add("DEFINES", ["DEFINES", "DESCRIBES", "EXPLAINS"])
_add("DEFINES", ["IS_DEFINED_BY", "IS_DEFINED_AS", "IS_DESCRIBED_BY", "IS_EXPLAINED_BY"], flip=True)
_add("HAS", ["HAS", "HAS_PARAMETER", "HAS_FEATURE", "HAS_ATTRIBUTE", "HAS_METHOD", "HAS_PROPERTY", "HAS_ARGUMENT", "HAS_COMPONENT"])
_add("CAUSES", ["CAUSES", "LEADS_TO", "RESULTS_IN"])
_add("BUILT_ON", ["BUILT_ON", "IS_BUILT_ON", "IS_BASED_ON", "BASED_ON", "EXTENDS", "BUILT_ON_TOP_OF"])
_add("PRODUCES", ["PRODUCES", "GENERATES", "RETURNS", "OUTPUTS", "YIELDS", "CREATES"])
_add("REQUIRES", ["REQUIRES", "DEPENDS_ON", "TAKES", "NEEDS", "REQUIRES_INPUT"])
_add("PROVIDES", ["PROVIDES", "COMES_WITH", "OFFERS", "SUPPLIES"])
_add("IMPLEMENTS", ["IMPLEMENTS", "IMPLEMENTED_IN", "IMPLEMENTED_BY"])
_add("PREDICTS", ["PREDICTS", "ESTIMATES", "CLASSIFIES"])
_add("DIFFERS_FROM", ["DIFFERS_FROM", "VS", "VERSUS", "COMPARED_TO", "CONTRASTS_WITH", "IS_DIFFERENT_FROM", "UNLIKE"])
_add("APPLIES_TO", ["APPLIES_TO", "APPLIED_TO", "APPLICABLE_TO", "IS_APPLIED_TO", "OPERATES_ON"])
_add("RELATED_TO", ["RELATED_TO", "IS_RELATED_TO", "IS_ASSOCIATED_WITH", "ASSOCIATED_WITH", "IS_RELEVANT_TO", "USED_WITH", "IS_USED_WITH", "WORKS_WITH", "CONNECTED_TO", "LINKED_TO"])


def normalize_predicate(raw: str | None) -> tuple[str, bool]:
    """Returns (predicate, flip). Unknown predicates are kept (sanitised) rather than collapsed, because rare
    ones like AUTHOR_OF or PUBLISHED_IN carry real information; flip=True means swap source and target."""
    key = re.sub(r"[^A-Z0-9]+", "_", (raw or "").upper()).strip("_")[:100]
    if not key:
        return "RELATED_TO", False
    return PREDICATE_MAP.get(key, (key, False))


# Entities that are layout or code scaffolding rather than knowledge: single letters (variables), x/y data
# variables from code listings, module aliases, and figure/chapter references.
_VARIABLE = re.compile(r"^[xy](_[a-z0-9]+)*$", re.IGNORECASE)
_STRUCTURAL = re.compile(
    r"^(figure|fig|table|chapter|section|page|listing|appendix|example)s?\.?(\s+[a-z]?\d+([.\-–][\da-z]+)*)?$",
    re.IGNORECASE)
_ALIASES = {"plt", "np", "pd", "df", "ax", "fig", "args", "kwargs", "self"}
_KEEP_SINGLE = {"c", "r"}  # programming languages / the SVM parameter


def is_noise_entity(name: str | None) -> bool:
    if not name:
        return True
    n = " ".join(name.split())
    low = n.lower()
    if len(low) == 1 and low not in _KEEP_SINGLE:
        return True
    return bool(low in _ALIASES or _VARIABLE.match(n) or _STRUCTURAL.match(n))


MAX_ENTITY_NAME_LEN = 100


def squash(text: str) -> str:
    """Lower-case and drop everything except letters, digits, '+' and '#' (so 'C++' stays distinct from 'C').
    'tf-idf', 'tf–idf', 'TF_IDF' and 'tf idf' all become 'tfidf'."""
    return "".join(c for c in unicodedata.normalize("NFKC", text).lower() if c.isalnum() or c in "+#")


# Names that link everything to everything and say nothing: kept in the graph, but discounted when ranking
# bridges or routing paths.
GENERIC_NAMES = {"data", "value", "values", "model", "models", "result", "results", "feature", "features", "input",
                 "output", "example", "examples", "number", "type", "function", "method", "methods", "set", "list",
                 "dataset", "datasets", "algorithm", "algorithms", "code", "python", "file", "files", "table"}


def is_generic_name(name: str | None) -> bool:
    key = squash(name or "")
    return len(key) <= 2 or key in GENERIC_NAMES


def canonicalize(name) -> str:
    """Key used to merge entities. Empty string means the name is unusable (not text, too long, no letters/digits)."""
    if not isinstance(name, str) or len(name) > MAX_ENTITY_NAME_LEN:
        return ""
    key = squash(name)
    return key if any(c.isalnum() for c in key) else ""
