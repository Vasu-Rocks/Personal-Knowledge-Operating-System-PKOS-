import pytest

from rag.graph.vocab import canonicalize, is_generic_name, is_noise_entity, normalize_predicate, squash


def test_squash_unifies_variants_but_keeps_cpp():
    assert squash("tf-idf") == squash("TF_IDF") == squash("tf idf") == "tfidf"
    assert squash("C++") != squash("C")


def test_canonicalize_rejects_unusable_names():
    assert canonicalize(None) == ""
    assert canonicalize("x" * 101) == ""
    assert canonicalize("---") == ""
    assert canonicalize("Random Forest") == "randomforest"


@pytest.mark.parametrize("raw,expected", [
    ("USES", ("USES", False)),
    ("is used by", ("USES", True)),
    ("part of", ("CONTAINS", True)),
    ("Author Of", ("AUTHOR_OF", False)),
    ("", ("RELATED_TO", False)),
    (None, ("RELATED_TO", False)),
])
def test_normalize_predicate(raw, expected):
    assert normalize_predicate(raw) == expected


@pytest.mark.parametrize("name", [None, "", "a", "x_1", "Figure 3.2", "Table", "np", "Chapter 4"])
def test_noise_entities(name):
    assert is_noise_entity(name)


@pytest.mark.parametrize("name", ["C", "Random Forest", "NumPy", "Figure skating"])
def test_real_entities_not_noise(name):
    assert not is_noise_entity(name)


def test_generic_names():
    assert is_generic_name("Data") and is_generic_name("ab")
    assert not is_generic_name("Gradient Boosting")
