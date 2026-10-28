from __future__ import annotations

import pytest

from triage.domain.taxonomy import CATEGORIES
from triage.kb.retrieve import KnowledgeBase, default_knowledge_base, load_articles, parse_article, tokens


def test_all_articles_parse_and_use_known_categories() -> None:
    articles = load_articles()
    assert len(articles) >= 19
    assert len({a.id for a in articles}) == len(articles)
    for a in articles:
        assert a.category in CATEGORIES
        assert a.title and a.body and a.keywords
        assert len(a.summary) < len(a.body) or "\n\n" not in a.body


def test_every_category_has_an_article() -> None:
    assert {a.category for a in load_articles()} == set(CATEGORIES)


@pytest.mark.parametrize(
    ("text", "category", "expected"),
    [
        ("forgot my password and can't sign in", "access", "KB001"),
        ("vpn keeps disconnecting when working from home", "network", "KB004"),
        ("printer says offline and nothing prints", "printing", "KB010"),
        ("suspicious email asking me to log in", "security", "KB012"),
        ("left my laptop on the train", "security", "KB013"),
        ("my mailbox is full and I can't send emails", "m365", "KB019"),
        ("no sound on my Teams call", "m365", "KB008"),
    ],
)
def test_search_finds_the_right_article(text: str, category: str, expected: str) -> None:
    hits = default_knowledge_base().search(text, category=category)
    assert hits and hits[0].article.id == expected


def test_search_returns_nothing_for_unrelated_text() -> None:
    assert default_knowledge_base().search("zebra quantum marmalade", category="access") == []


def test_other_categories_need_a_strong_match() -> None:
    kb = default_knowledge_base()
    # In its own category both printing articles match; from another category only the strong one does.
    assert [h.article.id for h in kb.search("printer toner", category="printing", k=5)] == ["KB017", "KB010"]
    assert [h.article.id for h in kb.search("printer toner", category="security", k=5)] == ["KB017"]


def test_tokens_fold_plurals_and_drop_function_words() -> None:
    assert tokens("my emails and printers") == ["email", "printer"]
    assert tokens("teams status access windows") == ["teams", "status", "access", "windows"]
    assert tokens("mailbox is full") == ["mailbox", "full"]  # "full" matters here


def test_parse_article_errors() -> None:
    with pytest.raises(ValueError, match="front matter"):
        parse_article("no front matter here")
    with pytest.raises(ValueError, match="not closed"):
        parse_article("---\nid: X\n")
    with pytest.raises(ValueError, match="missing"):
        parse_article("---\nid: X\n---\nbody")
    with pytest.raises(ValueError, match="at least one"):
        KnowledgeBase([])
