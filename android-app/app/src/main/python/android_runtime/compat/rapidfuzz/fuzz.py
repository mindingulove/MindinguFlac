from __future__ import annotations

from difflib import SequenceMatcher


def _text(value: object) -> str:
    return " ".join(str(value or "").casefold().split())


def ratio(left: object, right: object) -> float:
    return SequenceMatcher(None, _text(left), _text(right)).ratio() * 100.0


def token_sort_ratio(left: object, right: object) -> float:
    return ratio(" ".join(sorted(_text(left).split())), " ".join(sorted(_text(right).split())))


def token_set_ratio(left: object, right: object) -> float:
    left_tokens = set(_text(left).split())
    right_tokens = set(_text(right).split())
    common = left_tokens & right_tokens
    left_only = left_tokens - common
    right_only = right_tokens - common
    shared = " ".join(sorted(common))
    left_value = " ".join(filter(None, (shared, " ".join(sorted(left_only)))))
    right_value = " ".join(filter(None, (shared, " ".join(sorted(right_only)))))
    if not left_value and not right_value:
        return 100.0
    return max(ratio(shared, left_value), ratio(shared, right_value), ratio(left_value, right_value))


def WRatio(left: object, right: object) -> float:
    return max(ratio(left, right), token_sort_ratio(left, right) * 0.95, token_set_ratio(left, right) * 0.95)
