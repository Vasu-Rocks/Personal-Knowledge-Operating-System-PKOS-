import pytest

from rag.query.router import is_broad_query


@pytest.mark.parametrize("q", [
    "Give me an overview of the book",
    "What are the main topics covered?",
    "What is this book about?",
    "Summarize my documents",
    "List all the key concepts",
    "Compare ideas across all of my books",
])
def test_broad_questions(q):
    assert is_broad_query(q)


@pytest.mark.parametrize("q", [
    "What is gradient descent?",
    "How does the Adam optimizer update weights?",
    "Summarise chapter 2",
    "Explain figure 3.1",
])
def test_specific_questions(q):
    assert not is_broad_query(q)
