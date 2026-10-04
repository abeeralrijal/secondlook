"""Reader-facing transparency labels (planning.md section 3).

The only component that composes text a reader sees. Centralising it keeps the
wording from drifting and lets the spec be quoted verbatim.

Three things section 3 settled that this module enforces:

- **No numeric score in the label.** Confidence is an ordinal reliability
  score, not a probability. Rendering it as "87%" hands a non-technical reader
  the one reading it does not support. Every string here is static.
- **No severity field.** It duplicated `variant` and encoded a judgment that
  an AI result is a problem. Frontends style off `variant`.
- **`under_review` outranks any verdict.** An unreviewed accusation should not
  keep standing while it is being disputed.
"""

LABELS = {
    "high_confidence_ai": {
        "headline": "Likely AI-generated",
        "body": (
            "Two separate checks both found patterns typical of AI writing. One "
            "measured sentence rhythm, punctuation variety, and how often common "
            "transition phrases appear. The other read the text for the kind of "
            "phrasing and structure AI tends to produce."
        ),
        "confidence_phrase": (
            "Both checks agreed, and there was enough text to analyze properly, so "
            "this result is a strong one. It is still an automated estimate rather "
            "than proof of how the text was made. The creator can contest it."
        ),
    },
    "high_confidence_human": {
        "headline": "Likely written by a person",
        "body": (
            "Two separate checks both found patterns typical of human writing, "
            "including natural variation in sentence length and the kind of specific "
            "detail writers draw from their own experience."
        ),
        "confidence_phrase": (
            "Both checks agreed, and there was enough text to analyze properly, so "
            "this result is a strong one. It is an automated estimate, and it does "
            "not rule out AI help with drafting or editing."
        ),
    },
    "uncertain": {
        "headline": "Not enough evidence to say",
        "body": (
            "Our checks either disagreed with each other, or the text did not give "
            "them enough to work with, or the result was too close to call. The "
            "system could not reach a reliable conclusion."
        ),
        "confidence_phrase": (
            "No call is being made in either direction. Treat this as unknown, not "
            "as a reason for suspicion."
        ),
    },
    "under_review": {
        "headline": "Under review",
        "body": (
            "The creator has contested the earlier result. A person is reviewing it "
            "now."
        ),
        "confidence_phrase": (
            "The automated result is on hold until that review is finished."
        ),
    },
}

VERDICT_TO_VARIANT = {
    "ai": "high_confidence_ai",
    "human": "high_confidence_human",
    "uncertain": "uncertain",
}


def generate_label(verdict, confidence=None, status=None):
    """Map a classification outcome to the label a reader sees.

    `confidence` is accepted for interface symmetry and deliberately unused:
    the verdict already encodes the confidence gate, and section 3 removed
    every numeric value from reader-facing text.

    Never stored on a submission. Regenerated from current status on every
    read, which is what lets an appeal change the displayed label without
    rewriting the decision behind it.
    """
    if status == "under_review":
        variant = "under_review"
    else:
        variant = VERDICT_TO_VARIANT.get(verdict, "uncertain")
    return {"variant": variant, **LABELS[variant]}
