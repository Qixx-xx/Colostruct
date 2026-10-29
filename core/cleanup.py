"""Rule-based de-noising for Cantonese/English ASR transcripts.

The clinical context is a Hong Kong public hospital: dictation switches between
Cantonese, English medical terms, and Chinese particles, often without spaces
between the two languages.  This module removes only high-confidence noise; it
must never rewrite clinical meaning or delete a correction cue.

Rules
-----
A. Remove high-risk fillers:
   * English ``um``, ``uh``, ``er``, ``ah``, ``like``, ``you know`` as whole
     Latin words;
   * Cantonese interjections ``呃``, ``嗯``, ``呀``, ``啦``, ``囉``/``啰``,
     ``啫``, ``嗱`` when they end a token (before punctuation, whitespace, or
     the end of the segment);
   * Cantonese filler phrases ``即系``, ``即系话``, ``咁样`` and their
     Traditional-Chinese variants.
B. Never delete the ``呢`` in ``呢个``/``呢個``/``呢度``, or the ``咁`` in
   ``咁大``.  ``呢`` is only removed as a sentence-final particle, and ``咁``
   is never removed on its own; only the exact phrase ``咁样``/``咁樣`` is
   removed.  This also keeps meaningful uses such as ``唔係咁`` intact.
C. Never filter contrast/correction cues such as ``但系``, ``唔系``, ``其实``,
   ``but``, ``actually``, ``wait``, and ``however``.  Those words are evidence
   for the later temporal-override pass, not filler.
D. Collapse consecutive repeated words: ``我我我`` -> ``我``,
   ``is is is`` -> ``is``.  Chinese single-character repeats are collapsed only
   at three or more occurrences, so legitimate reduplication such as ``慢慢``
   or ``常常`` is preserved.

Punctuation is always retained, and a segment whose text becomes empty keeps
its ``segment_id``, ``start``, and ``end`` so the timeline never develops a gap.

Example
-------
.. code-block::

    >>> clean_transcript([
    ...     {
    ...         "segment_id": "seg-001",
    ...         "text": "呃...呢個 tumour 呢，um...大概 3 cm 啦",
    ...         "start": 0.0,
    ...         "end": 2.0,
    ...     }
    ... ])[0]["text"]
    '...呢個 tumour，...大概 3 cm'
"""

from __future__ import annotations

import re
from typing import Final

__all__ = [
    "EN_CONTRAST_WORDS",
    "EN_FILLERS",
    "YUE_CONTRAST_WORDS",
    "YUE_FILLERS",
    "YUE_FILLER_PHRASES",
    "YUE_PROTECTED_PHRASES",
    "YUE_SENTENCE_FINAL_PARTICLES",
    "clean_transcript",
]


#: English fillers removed as whole Latin words.  ``you know`` is matched with
#: flexible whitespace because ASR may emit one or more spaces.
EN_FILLERS: Final[tuple[str, ...]] = (
    "you know",
    "um",
    "uh",
    "er",
    "ah",
    "like",
)

#: Cantonese interjections removed when they end a token.  ``囉`` and ``啰``
#: are the Traditional and Simplified forms of the same particle.
YUE_FILLERS: Final[tuple[str, ...]] = (
    "呃",
    "嗯",
    "呀",
    "啦",
    "囉",
    "啰",
    "啫",
    "嗱",
)

#: ``呢`` is a common sentence-final filler, but it is also the demonstrative
#: in ``呢個``/``呢个`` and ``呢度``.  It is therefore removed only when it is
#: followed by punctuation, whitespace, or the end of the segment.
YUE_SENTENCE_FINAL_PARTICLES: Final[tuple[str, ...]] = ("呢",)


#: Multi-character Cantonese filler phrases.  Traditional and mixed
#: Traditional/Simplified variants are included because Hong Kong ASR output
#: is not guaranteed to use one character set consistently.
YUE_FILLER_PHRASES: Final[tuple[str, ...]] = (
    "即系话",
    "即係話",
    "即系話",
    "即係话",
    "咁样",
    "咁樣",
    "即系",
    "即係",
)

#: Phrases that must survive cleaning even though they contain a character
#: that also appears in a filler.  They are deliberately protected by the
#: regex design and asserted in the tests below.
YUE_PROTECTED_PHRASES: Final[tuple[str, ...]] = (
    "呢个",
    "呢個",
    "呢度",
    "咁大",
)

#: Correction/contrast cues that later passes use to detect a doctor changing
#: their mind.  They are never part of any removal pattern.
YUE_CONTRAST_WORDS: Final[tuple[str, ...]] = (
    "但系",
    "但係",
    "不过",
    "不過",
    "唔系",
    "唔係",
    "其实",
    "其實",
    "等阵",
    "等陣",
    "但是",
    "不对",
    "不對",
)

#: English correction/contrast cues.  They are documented here and guarded by
#: tests, even though no filler pattern can match them.
EN_CONTRAST_WORDS: Final[tuple[str, ...]] = (
    "but",
    "actually",
    "wait",
    "however",
)


#: Characters that can bound a Cantonese particle.  Whitespace and the common
#: Chinese/English punctuation marks are included; quotes are included so that
#: ``"啦"`` is cleaned without deleting the quotation marks.
_BOUNDARY_CHARS: Final[str] = r"\s，,。.！!？?；;：:、…\(\)\[\]】\"'“”‘’"

#: A particle is removable when it is followed by a boundary or the end of the
#: segment.  This suffix-only rule is what allows ``好啦。`` and ``係呀。`` to be
#: cleaned while keeping ``呃人`` (the verb "to deceive") intact.
_PARTICLE_END: Final[str] = rf"(?=$|[{_BOUNDARY_CHARS}])"


def _alternation(items: tuple[str, ...]) -> str:
    """Build an escaped regex alternation, longest item first.

    Longest-first ordering prevents a short phrase such as ``即系`` from
    consuming the prefix of ``即系话`` and leaving a dangling ``话``.
    """
    return "|".join(re.escape(item) for item in sorted(items, key=len, reverse=True))


def _english_filler_pattern() -> str:
    """Build the whole-word English filler pattern.

    ``(?<![A-Za-z])`` / ``(?![A-Za-z])`` are used instead of ``\\b`` because
    Cantonese and English are often adjacent without a space (``um大概``).
    ``\\b`` would treat the Chinese character as a word character and refuse
    the match; the Latin-letter lookarounds handle the mixed-script case.
    """
    words = "|".join(
        r"\s+".join(re.escape(part) for part in filler.split())
        for filler in sorted(EN_FILLERS, key=len, reverse=True)
    )
    return rf"(?<![A-Za-z])(?:{words})(?![A-Za-z])"


def _cantonese_filler_pattern() -> str:
    """Build the Cantonese interjection pattern.

    ``呀`` is also the tail of the interjections ``哎呀`` and ``唉呀``.  The
    negative lookbehind keeps those meaningful exclamations intact.
    """
    parts: list[str] = []
    for filler in sorted(YUE_FILLERS, key=len, reverse=True):
        if filler == "呀":
            parts.append(r"(?<![哎唉])呀")
        else:
            parts.append(re.escape(filler))
    return "|".join(parts)


_EN_FILLER_RE: Final[re.Pattern[str]] = re.compile(
    _english_filler_pattern(),
    re.IGNORECASE,
)
_YUE_PHRASE_RE: Final[re.Pattern[str]] = re.compile(
    _alternation(YUE_FILLER_PHRASES),
)
_YUE_FILLER_RE: Final[re.Pattern[str]] = re.compile(
    rf"(?:{_cantonese_filler_pattern()}){_PARTICLE_END}",
)
_YUE_FINAL_PARTICLE_RE: Final[re.Pattern[str]] = re.compile(
    rf"(?:{_alternation(YUE_SENTENCE_FINAL_PARTICLES)})"
    rf"(?!\s*(?:個|个|度)){_PARTICLE_END}",
)

# English repeated words may be separated by spaces/newlines.  The first
# occurrence is kept, including its original case.
_REPEATED_EN_WORD_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(\w+)(?:\s+\1\b)+",
    re.IGNORECASE,
)

# Chinese single-character repeats are collapsed only at three or more
# occurrences.  Two-character reduplication is real vocabulary far too often
# (慢慢, 常常, 看看) to be treated as a stutter.
_REPEATED_ZH_CHAR_RE: Final[re.Pattern[str]] = re.compile(
    r"([\u4e00-\u9fff])\1{2,}",
)

_WHITESPACE_RE: Final[re.Pattern[str]] = re.compile(r"\s+")
_SPACE_BEFORE_PUNCT_RE: Final[re.Pattern[str]] = re.compile(
    r" +([，,。.！!？?；;：:、…])",
)


def _clean_text(text: str) -> str:
    """Apply the full cleaning pipeline to one transcript segment.

    The order is intentional: collapsing repeats first turns ``um um um`` into
    a single ``um`` that the filler pattern can then remove, and turns
    ``啦啦啦`` into ``啦`` before the sentence-final particle rule runs.

    Args:
        text: Raw ASR text for one segment.

    Returns:
        Cleaned text with original punctuation retained.  The result may be an
        empty string when the segment contained only fillers.
    """
    cleaned = text

    # Rule D first: repeated fillers become a single removable token.
    cleaned = _REPEATED_EN_WORD_RE.sub(r"\1", cleaned)
    cleaned = _REPEATED_ZH_CHAR_RE.sub(r"\1", cleaned)

    # Rule A: phrases before single characters so 即系话 is not half-removed.
    cleaned = _YUE_PHRASE_RE.sub("", cleaned)
    cleaned = _EN_FILLER_RE.sub("", cleaned)
    cleaned = _YUE_FILLER_RE.sub("", cleaned)
    cleaned = _YUE_FINAL_PARTICLE_RE.sub("", cleaned)

    # Cosmetic whitespace only: punctuation itself is never removed.
    cleaned = _WHITESPACE_RE.sub(" ", cleaned)
    cleaned = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", cleaned)
    return cleaned.strip()


def clean_transcript(segments: list[dict]) -> list[dict]:
    """Clean ASR text while preserving every segment's timeline metadata.

    Each input dict is shallow-copied, so ``segment_id``, ``start``, ``end``,
    and any additional caller-owned keys are preserved unchanged.  Only the
    ``text`` key is replaced.  A segment whose text becomes empty stays in the
    returned list with ``"text": ""``; this is required so the offset table and
    audio timeline remain continuous.

    Args:
        segments: ASR segments in timeline order, each containing at least
            ``segment_id``, ``text``, ``start``, and ``end``.

    Returns:
        A new list with the same length and order as ``segments``.  The input
        list and its dictionaries are not mutated.

    Raises:
        TypeError: If a segment is not a dictionary.
    """
    cleaned_segments: list[dict] = []

    for segment in segments:
        if not isinstance(segment, dict):
            raise TypeError(
                f"Each transcript segment must be a dict, got {type(segment).__name__}"
            )

        cleaned_segment = dict(segment)
        raw_text = segment.get("text", "")
        cleaned_segment["text"] = (
            _clean_text(raw_text) if isinstance(raw_text, str) else ""
        )
        cleaned_segments.append(cleaned_segment)

    return cleaned_segments


if __name__ == "__main__":
    import json

    segments = [
        {
            "segment_id": "seg-001",
            "text": "呃...呢個 tumour 呢，um...大概 3 cm 啦",
            "start": 0.0,
            "end": 2.0,
        },
        {
            "segment_id": "seg-002",
            "text": "但係我睇到 is is is 4 cm，actually wait，唔係，其實 5 cm。",
            "start": 2.0,
            "end": 5.0,
        },
        {
            "segment_id": "seg-003",
            "text": "呢度有 3 粒，咁大個瘤。",
            "start": 5.0,
            "end": 7.0,
        },
        {
            "segment_id": "seg-004",
            "text": "um uh",
            "start": 7.0,
            "end": 7.5,
        },
    ]

    cleaned = clean_transcript(segments)

    print("BEFORE")
    print(json.dumps(segments, ensure_ascii=False, indent=2))
    print("\nAFTER")
    print(json.dumps(cleaned, ensure_ascii=False, indent=2))

    # Timeline structure must be identical, including the segment that became
    # empty.  These assertions also keep the example executable as a test.
    assert len(cleaned) == len(segments)
    assert [item["segment_id"] for item in cleaned] == [
        item["segment_id"] for item in segments
    ]
    assert [(item["start"], item["end"]) for item in cleaned] == [
        (item["start"], item["end"]) for item in segments
    ]

    # Protected demonstratives and the protected 咁大 phrase survive.
    assert "呢個" in cleaned[0]["text"]
    assert "呢度" in cleaned[2]["text"]
    assert "咁大" in cleaned[2]["text"]

    # Correction cues are never removed.
    for cue in ("但係", "唔係", "其實"):
        assert cue in cleaned[1]["text"]
    for cue in ("actually", "wait"):
        assert cue in cleaned[1]["text"]

    # Repeated English words collapse to one occurrence.
    assert "is is is" not in cleaned[1]["text"]
    assert "is 4 cm" in cleaned[1]["text"]

    # A segment made only of fillers keeps its metadata and gets empty text.
    assert cleaned[3]["text"] == ""
    assert cleaned[3]["segment_id"] == "seg-004"
    assert cleaned[3]["start"] == 7.0
    assert cleaned[3]["end"] == 7.5

    # Anti-false-deletion checks that are easy to regress when editing regexes.
    edge_cases = {
        "哎呀，好痛呀。": "哎呀，好痛。",  # 哎呀 is an interjection, not filler + 呀
        "呃人嘅。": "呃人嘅。",  # 呃人 = to deceive; do not strip the verb
        "唔係咁。": "唔係咁。",  # 咁 is meaningful here, not a filler
        "慢慢": "慢慢",  # two-character reduplication is real vocabulary
        "我我我": "我",  # three repetitions are a stutter
        "um大概": "大概",  # mixed-script whole-word match without a space
        "呢個呢，": "呢個，",  # sentence-final 呢 removed, demonstrative kept
        "即系话": "",  # whole filler phrase, not a half-removed prefix
        "咁樣": "",  # Traditional-Chinese variant
    }
    for raw, expected in edge_cases.items():
        actual = clean_transcript(
            [{"segment_id": "edge", "text": raw, "start": 0.0, "end": 1.0}]
        )[0]["text"]
        assert actual == expected, f"{raw!r}: expected {expected!r}, got {actual!r}"

    # Every configured filler must actually be removed when it stands alone.
    for filler in EN_FILLERS + YUE_FILLERS + YUE_FILLER_PHRASES:
        actual = clean_transcript(
            [{"segment_id": "filler", "text": filler, "start": 0.0, "end": 1.0}]
        )[0]["text"]
        assert actual == "", f"filler not removed: {filler!r} -> {actual!r}"

    # Every configured protected phrase and contrast cue must survive.
    for cue in YUE_PROTECTED_PHRASES + YUE_CONTRAST_WORDS + EN_CONTRAST_WORDS:
        actual = clean_transcript(
            [{"segment_id": "cue", "text": cue, "start": 0.0, "end": 1.0}]
        )[0]["text"]
        assert cue in actual, f"protected cue lost: {cue!r} -> {actual!r}"

    print("\nAll cleanup assertions passed, including edge cases and vocabulary.")
