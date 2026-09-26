"""Title/author matching, shared by every Source's resolution step (ADR 8)."""

from .matcher import (
    Candidate,
    Confidence,
    OriginalTitleLookup,
    Query,
    Resolution,
    Scored,
    author_matches,
    authors_contradict,
    by_original_title,
    match,
    needs_original_title,
    score,
    worth_confirming,
)
from .normalize import fold, normalize_author, normalize_authors, normalize_title, split_authors

__all__ = [
    "Candidate",
    "Confidence",
    "OriginalTitleLookup",
    "Query",
    "Resolution",
    "Scored",
    "author_matches",
    "authors_contradict",
    "by_original_title",
    "fold",
    "match",
    "needs_original_title",
    "normalize_author",
    "normalize_authors",
    "normalize_title",
    "score",
    "split_authors",
    "worth_confirming",
]
