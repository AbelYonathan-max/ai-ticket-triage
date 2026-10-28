"""Find the knowledge base articles that best match a ticket.

The articles are short Markdown files with a small front matter block. Retrieval is TF-IDF with
cosine similarity, restricted to the category the classifier predicted unless an article from another
category matches strongly. That is enough for a small knowledge base, runs in under a millisecond, and
every match can be explained. The articles are also what the language model is allowed to cite, so its
reply drafts stay grounded in approved text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources

from sklearn.feature_extraction.text import TfidfVectorizer

from triage.ml.model import normalise

MIN_SCORE = 0.10  # for articles in the predicted category; weaker matches were mostly unrelated
MIN_SCORE_OTHER = 0.25  # an article from another category has to match much more strongly

# A short list of function words. scikit-learn's built-in English list also drops words that matter in
# IT tickets, such as "full", "empty", "call", "system" and "show".
STOP_WORDS = frozenset(
    """a about after again all also am an and any are as at be been before being but by can could did didn
    do doe doesn doing don for from had has have having he her here him his how if in into is isn it its just
    ll me my myself no nor not of on once only or other our out over own please same she should so some
    such than thank that the their them then there these they this those through to too under until up
    ve very wasn we were what when where which while who whom why will with won would you your hi hello
    regard cheer""".split()  # noqa: SIM905 - easier to read than a list literal
)
# Words that look plural but should keep their "s": Microsoft Teams is not a team, Windows is not a window.
_KEEP_S = frozenset({"teams", "windows", "always", "sometimes", "series", "status", "news", "yes", "bus"})
_TOKEN = re.compile(r"(?u)\b\w\w+\b")


def tokens(text: str) -> list[str]:
    """Words, with a light plural fold so "emails" matches "email" and "printers" matches "printer"."""
    words = []
    for word in _TOKEN.findall(text):
        if (
            len(word) > 3
            and word.endswith("s")
            and not word.endswith(("ss", "us", "is"))
            and word not in _KEEP_S
        ):
            word = word[:-1]
        if word not in STOP_WORDS:
            words.append(word)
    return words


@dataclass(frozen=True)
class Article:
    id: str
    title: str
    category: str
    keywords: tuple[str, ...]
    body: str

    @property
    def summary(self) -> str:
        """The first paragraph, used on the result page and in the language model prompt."""
        return self.body.strip().split("\n\n", 1)[0]


@dataclass(frozen=True)
class KbHit:
    article: Article
    score: float


def parse_article(text: str) -> Article:
    """Parse an article: a front matter block between two '---' lines, then the Markdown body."""
    lines = text.strip().splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("article must start with a front matter block")
    end = next((i for i, line in enumerate(lines[1:], start=1) if line.strip() == "---"), None)
    if end is None:
        raise ValueError("front matter block is not closed")
    meta: dict[str, str] = {}
    for line in lines[1:end]:
        key, sep, value = line.partition(":")
        if not sep:
            raise ValueError(f"bad front matter line: {line!r}")
        meta[key.strip()] = value.strip()
    missing = {"id", "title", "category", "keywords"} - meta.keys()
    if missing:
        raise ValueError(f"front matter is missing {sorted(missing)}")
    return Article(
        id=meta["id"],
        title=meta["title"],
        category=meta["category"],
        keywords=tuple(k.strip() for k in meta["keywords"].split(",") if k.strip()),
        body="\n".join(lines[end + 1 :]).strip(),
    )


def load_articles() -> list[Article]:
    folder = resources.files("triage.kb").joinpath("articles")
    articles = [
        parse_article(f.read_text(encoding="utf-8")) for f in folder.iterdir() if f.name.endswith(".md")
    ]
    return sorted(articles, key=lambda a: a.id)


class KnowledgeBase:
    def __init__(self, articles: list[Article]) -> None:
        if not articles:
            raise ValueError("the knowledge base needs at least one article")
        self.articles = articles
        self._by_id = {a.id: a for a in articles}
        self._vectorizer = TfidfVectorizer(
            sublinear_tf=True, ngram_range=(1, 2), tokenizer=tokens, token_pattern=None, lowercase=False
        )
        # Titles and keywords are repeated so they count for more than the body text.
        docs = [
            normalise(f"{a.title} {a.title} {' '.join(a.keywords)} {' '.join(a.keywords)} {a.body}")
            for a in articles
        ]
        self._matrix = self._vectorizer.fit_transform(docs)

    def get(self, article_id: str) -> Article | None:
        return self._by_id.get(article_id)

    def search(self, text: str, category: str | None = None, k: int = 3) -> list[KbHit]:
        """Best matching articles. With a predicted category, articles from that category are preferred
        and an article from another category is only suggested when it matches strongly."""
        query = self._vectorizer.transform([normalise(text)])
        similarity = (self._matrix @ query.T).toarray().ravel()
        scored = []
        for i, article in enumerate(self.articles):
            same = category is None or article.category == category
            if similarity[i] >= (MIN_SCORE if same else MIN_SCORE_OTHER):
                scored.append((not same, -float(similarity[i]), i))
        scored.sort()
        return [KbHit(self.articles[i], round(-neg, 3)) for _, neg, i in scored[:k]]


@lru_cache(maxsize=1)
def default_knowledge_base() -> KnowledgeBase:
    return KnowledgeBase(load_articles())
