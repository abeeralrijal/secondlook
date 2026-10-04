"""Signal 1: stylometric variance (planning.md section 1).

Local computation, no network. Four sub-metrics, each normalized to a [0, 1]
AI-likeness value through a clamped linear ramp, then combined by fixed weights.

Returns a continuous score, not a binary flag. The confidence model in section 2
needs to know how strongly the signal leans, not only which way.
"""

import math
import re

import config

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])[\"')\]]*\s+")
_WORD = re.compile(r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*")
_ELLIPSIS = re.compile(r"\.{3}|…")


def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, value))


def _ramp(value, human_anchor, ai_anchor):
    """Map a raw metric onto [0, 1] AI-likeness.

    Handles either direction: ai_anchor may be below human_anchor (burstiness,
    where lower is more AI-like) or above it (discourse markers, where higher
    is more AI-like).
    """
    span = ai_anchor - human_anchor
    if span == 0:
        return 0.0
    return _clamp((value - human_anchor) / span)


def _coefficient_of_variation(values):
    """Return stdev / mean, or None where it is not defined.

    Guarded on both counts: the sample standard deviation needs at least two
    observations, and the division needs a non-zero mean.
    """
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    if mean <= 0:
        return None
    variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(variance) / mean


def _split_sentences(text):
    parts = [p.strip() for p in _SENTENCE_SPLIT.split(text)]
    return [p for p in parts if _WORD.search(p)]


def _split_paragraphs(text):
    parts = [p.strip() for p in re.split(r"\n\s*\n", text)]
    return [p for p in parts if _WORD.search(p)]


def _words(text):
    return _WORD.findall(text)


def _punctuation_entropy(text):
    """Shannon entropy over the punctuation class distribution, in bits."""
    working = _ELLIPSIS.sub("\u0000", text)
    counts = {}
    for cls in config.PUNCTUATION_CLASSES:
        if cls == "...":
            n = working.count("\u0000")
        elif cls == "-":
            n = len(re.findall(r"[-–—]", working))
        else:
            n = working.count(cls)
        if n:
            counts[cls] = n

    total = sum(counts.values())
    if total < config.MIN_PUNCTUATION_MARKS_FOR_ENTROPY:
        return None, total
    entropy = -sum(
        (n / total) * math.log2(n / total) for n in counts.values()
    )
    return entropy, total


def _discourse_density(text, word_count):
    lowered = text.lower()
    hits = 0
    for marker in config.DISCOURSE_MARKERS:
        hits += len(re.findall(r"\b" + re.escape(marker) + r"\b", lowered))
    return (hits * 100.0) / word_count, hits


def stylometric_signal(text):
    """Score text for AI-likeness on local statistics alone.

    Returns the uniform signal shape from planning.md section 1. Sub-metrics
    that cannot be measured on this text are reported unavailable and their
    weight is redistributed across the rest, rather than being filled with a
    default that would amount to a fabricated observation.
    """
    sentences = _split_sentences(text)
    paragraphs = _split_paragraphs(text)
    words = _words(text)
    word_count = len(words)

    components = {}
    reasons = []

    # --- Burstiness -------------------------------------------------------
    sentence_lengths = [len(_words(s)) for s in sentences]
    if len(sentences) < config.MIN_SENTENCES_FOR_BURSTINESS:
        components["burstiness"] = {
            "available": False,
            "why": f"needs {config.MIN_SENTENCES_FOR_BURSTINESS} sentences, found {len(sentences)}",
        }
    else:
        cv = _coefficient_of_variation(sentence_lengths)
        if cv is None:
            components["burstiness"] = {"available": False, "why": "undefined mean"}
        else:
            score = _ramp(cv, config.BURSTINESS_HUMAN_ANCHOR, config.BURSTINESS_AI_ANCHOR)
            components["burstiness"] = {
                "available": True,
                "raw": round(cv, 4),
                "score": round(score, 4),
                "weight": config.SUB_WEIGHT_BURSTINESS,
            }
            if score >= 0.7:
                reasons.append(
                    f"Sentence length barely varies across {len(sentences)} sentences."
                )
            elif score <= 0.3:
                reasons.append(
                    f"Sentence length varies a lot across {len(sentences)} sentences."
                )

    # --- Discourse markers ------------------------------------------------
    if word_count < config.MIN_WORDS_FOR_DISCOURSE_DENSITY:
        components["discourse_markers"] = {
            "available": False,
            "why": f"needs {config.MIN_WORDS_FOR_DISCOURSE_DENSITY} words, found {word_count}",
        }
    else:
        density, hits = _discourse_density(text, word_count)
        score = _ramp(density, config.DISCOURSE_HUMAN_ANCHOR, config.DISCOURSE_AI_ANCHOR)
        components["discourse_markers"] = {
            "available": True,
            "raw": round(density, 4),
            "hits": hits,
            "score": round(score, 4),
            "weight": config.SUB_WEIGHT_DISCOURSE_MARKERS,
        }
        if score >= 0.7:
            reasons.append(
                f"Frequent use of stock transition phrases ({hits} in {word_count} words)."
            )

    # --- Punctuation entropy ----------------------------------------------
    entropy, mark_count = _punctuation_entropy(text)
    if entropy is None:
        components["punctuation_entropy"] = {
            "available": False,
            "why": f"needs {config.MIN_PUNCTUATION_MARKS_FOR_ENTROPY} marks, found {mark_count}",
        }
    else:
        score = _ramp(
            entropy, config.PUNCTUATION_HUMAN_ANCHOR, config.PUNCTUATION_AI_ANCHOR
        )
        components["punctuation_entropy"] = {
            "available": True,
            "raw": round(entropy, 4),
            "score": round(score, 4),
            "weight": config.SUB_WEIGHT_PUNCTUATION_ENTROPY,
        }
        if score >= 0.7:
            reasons.append("Punctuation is almost entirely full stops and commas.")

    # --- Paragraph uniformity ---------------------------------------------
    if len(paragraphs) < config.MIN_PARAGRAPHS_FOR_UNIFORMITY:
        components["paragraph_uniformity"] = {
            "available": False,
            "why": f"needs {config.MIN_PARAGRAPHS_FOR_UNIFORMITY} paragraphs, found {len(paragraphs)}",
        }
    else:
        cv = _coefficient_of_variation([len(_words(p)) for p in paragraphs])
        if cv is None:
            components["paragraph_uniformity"] = {
                "available": False,
                "why": "undefined mean",
            }
        else:
            score = _ramp(cv, config.PARAGRAPH_HUMAN_ANCHOR, config.PARAGRAPH_AI_ANCHOR)
            components["paragraph_uniformity"] = {
                "available": True,
                "raw": round(cv, 4),
                "score": round(score, 4),
                "weight": config.SUB_WEIGHT_PARAGRAPH_UNIFORMITY,
            }
            if score >= 0.7:
                reasons.append("Paragraphs are near-identical in length.")

    # --- Combine ----------------------------------------------------------
    usable = [c for c in components.values() if c["available"]]
    if not usable:
        return {
            "name": "stylometric",
            "score": None,
            "weight": config.STYLOMETRIC_WEIGHT,
            "status": "failed",
            "reasons": ["Text did not support any of the statistical measures."],
            "components": components,
        }

    total_weight = sum(c["weight"] for c in usable)
    score = sum(c["score"] * c["weight"] for c in usable) / total_weight

    # Section 1 specifies the signal weight is "reduced on partial failure".
    # A score built from 60% of the intended sub-metric basis should not carry
    # the same weight in fusion as one built from all of it.
    effective_weight = round(config.STYLOMETRIC_WEIGHT * total_weight, 4)

    unavailable = [k for k, c in components.items() if not c["available"]]
    if unavailable:
        reasons.append(
            "Measured on "
            + str(len(usable))
            + " of 4 statistics; "
            + ", ".join(unavailable)
            + " could not be computed."
        )
    if not reasons:
        reasons.append("No single statistic stood out in either direction.")

    return {
        "name": "stylometric",
        "score": round(_clamp(score), 4),
        "weight": effective_weight,
        "nominal_weight": config.STYLOMETRIC_WEIGHT,
        "status": "ok",
        "reasons": reasons,
        "components": components,
        "measured_weight_fraction": round(total_weight, 4),
    }
