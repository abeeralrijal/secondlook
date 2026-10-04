"""Fusion and confidence (planning.md section 2).

Produces two numbers that are deliberately not the same quantity:

- `ai_likelihood` answers which way the evidence points.
- `confidence` answers how much weight that answer should carry.

Keeping them separate is what lets the system distinguish strong agreement
near the midpoint from strong disagreement averaging to the midpoint. A single
blended score cannot, and those two cases need different labels.
"""

import config


def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, value))


def _usable(signal):
    return bool(signal) and signal.get("status") == "ok" and signal.get("score") is not None


def _qualified_agreement_applies(judge):
    """True when the judge's evidence duplicates the stylometric signal.

    Section 2: agreement counts fully only when the judge fired a category
    that is genuinely independent of sentence length variance. If everything
    it fired is structural or register based, the two signals measured the
    same property and agreeing is not corroboration.

    An empty category list does not trigger this. Firing nothing means the
    judge found no AI indicator at all, which is a real observation rather
    than a duplicated one.
    """
    fired = set(judge.get("categories_fired") or [])
    if not fired:
        return False
    return fired.issubset(set(config.JUDGE_CORRELATED_CATEGORIES))


def _formality_damper_applies(stylometric):
    """True for text that is both flat in rhythm and plain in punctuation.

    This is the class section 5 identifies as the system's worst false
    positive: polished, formal, edited, or non-native-authored prose, which
    reads as AI to both signals for reasons that are not independent.
    """
    components = (stylometric or {}).get("components") or {}
    burst = components.get("burstiness") or {}
    punct = components.get("punctuation_entropy") or {}
    if not (burst.get("available") and punct.get("available")):
        return False
    return (
        burst["score"] >= config.FORMALITY_BURSTINESS_MIN
        and punct["score"] >= config.FORMALITY_PUNCTUATION_MIN
    )


def fuse(stylometric, judge, char_count):
    """Combine both signals into a likelihood, a confidence, and a verdict."""
    s1_ok, s2_ok = _usable(stylometric), _usable(judge)
    s1 = stylometric.get("score") if s1_ok else None
    s2 = judge.get("score") if s2_ok else None
    rules_fired = []

    if not s1_ok and not s2_ok:
        # No signal produced a score. This is still a classification outcome
        # rather than a server fault: the system looked and cannot say. The
        # uncertain label covers it in so many words, and signals[].status
        # tells a caller whether the cause was thin text or an outage.
        return {
            "ai_likelihood": None,
            "confidence": 0.0,
            "verdict": "uncertain",
            "rules_fired": ["no_signal_scored"],
            "components": {
                "agreement": None,
                "extremity": None,
                "sufficiency": round(_clamp(
                    (char_count - config.SUFFICIENCY_MIN_CHARS)
                    / (config.SUFFICIENCY_FULL_CHARS - config.SUFFICIENCY_MIN_CHARS)
                ), 4),
                "completeness": 0.0,
                "raw_confidence": 0.0,
            },
        }

    # --- Likelihood -------------------------------------------------------
    if s1_ok and s2_ok:
        ai_likelihood = (
            config.STYLOMETRIC_WEIGHT * s1 + config.JUDGE_WEIGHT * s2
        )
        completeness = config.COMPLETENESS_FULL
    else:
        ai_likelihood = s1 if s1_ok else s2
        completeness = config.COMPLETENESS_DEGRADED
        rules_fired.append(
            "degraded_stylometric_only" if s1_ok else "degraded_judge_only"
        )

    # --- Confidence components -------------------------------------------
    if s1_ok and s2_ok:
        agreement = 1.0 - abs(s1 - s2)
        if _qualified_agreement_applies(judge):
            agreement *= config.QUALIFIED_AGREEMENT_FACTOR
            rules_fired.append("qualified_agreement")
    else:
        agreement = config.AGREEMENT_WHEN_SINGLE_SIGNAL

    extremity = 2.0 * abs(ai_likelihood - 0.5)
    sufficiency = _clamp(
        (char_count - config.SUFFICIENCY_MIN_CHARS)
        / (config.SUFFICIENCY_FULL_CHARS - config.SUFFICIENCY_MIN_CHARS)
    )

    raw_confidence = (
        config.CONF_WEIGHT_AGREEMENT * agreement
        + config.CONF_WEIGHT_EXTREMITY * extremity
        + config.CONF_WEIGHT_SUFFICIENCY * sufficiency
    )
    confidence = raw_confidence * completeness

    if _formality_damper_applies(stylometric):
        if confidence > config.FORMALITY_CONFIDENCE_CAP:
            confidence = config.FORMALITY_CONFIDENCE_CAP
        rules_fired.append("formality_damper")

    # --- Verdict ----------------------------------------------------------
    # Both gates must clear. A decisive likelihood with thin confidence is
    # uncertain, and so is a confident reading that landed mid-scale.
    if (
        ai_likelihood >= config.VERDICT_AI_LIKELIHOOD_MIN
        and confidence >= config.VERDICT_CONFIDENCE_MIN
    ):
        verdict = "ai"
    elif (
        ai_likelihood <= config.VERDICT_HUMAN_LIKELIHOOD_MAX
        and confidence >= config.VERDICT_CONFIDENCE_MIN
    ):
        verdict = "human"
    else:
        verdict = "uncertain"

    return {
        "ai_likelihood": round(ai_likelihood, 4),
        "confidence": round(confidence, 4),
        "verdict": verdict,
        "rules_fired": rules_fired,
        "components": {
            "agreement": round(agreement, 4),
            "extremity": round(extremity, 4),
            "sufficiency": round(sufficiency, 4),
            "completeness": completeness,
            "raw_confidence": round(raw_confidence, 4),
        },
    }
