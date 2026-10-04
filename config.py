"""Every tunable constant in the system.

No numeric literal governing behaviour belongs anywhere else. Section 10 of
planning.md commits to replacing the ramp anchors with values measured on a
calibration corpus, and that has to be a config edit rather than a search
through the codebase.
"""

RULESET_VERSION = "0.3.0-m3"

# --- Validation bounds -----------------------------------------------------

# The validation floor and the confidence ramp answer different questions,
# and tying them together was a mistake. This one asks whether the text can
# be analyzed at all. Below roughly 50 characters no signal has anything to
# work with. Between 50 and a few hundred, the judge can still read the text
# even though the stylometric measures cannot run, and the right output is a
# low-confidence "not enough evidence to say" rather than a 400.
MIN_TEXT_CHARS = 50
MAX_TEXT_CHARS = 20_000

ALLOWED_CONTENT_TYPES = ("poem", "story", "blog_post", "other")
DEFAULT_CONTENT_TYPE = "other"

MAX_CREATOR_ID_CHARS = 64

# Appeals (planning.md section 4). The reasoning floor exists because an
# appeal with no argument gives a human reviewer nothing to act on.
MIN_REASONING_CHARS = 20
MAX_REASONING_CHARS = 5000
APPEAL_RATE_LIMITS = "5 per minute;20 per hour"
CONTENT_RATE_LIMITS = "60 per minute"

# Sufficiency ramp (planning.md section 2), deliberately independent of the
# validation floor above. This asks at what length text starts carrying
# enough information to trust a verdict, which is a far higher bar than
# "analyzable at all".
SUFFICIENCY_MIN_CHARS = 120
SUFFICIENCY_FULL_CHARS = 1120

# Provisional single-signal reading, used only until fusion exists. These are
# deliberately looser than the section 2 verdict gates, which require both
# signals plus confidence >= 0.75.
PROVISIONAL_AI_THRESHOLD = 0.70
PROVISIONAL_HUMAN_THRESHOLD = 0.30

# --- Audit log -------------------------------------------------------------
# JSON Lines rather than SQLite: the log is append-only by requirement, and
# one JSON object per line is append-only by construction. There is no
# UPDATE statement to misuse and no schema migration when M4 and M5 add
# fields. It stays greppable from a terminal, which matters for the
# reviewer queue in section 4.
AUDIT_LOG_PATH = "audit_log.jsonl"
AUDIT_LOG_DEFAULT_LIMIT = 50
AUDIT_LOG_MAX_LIMIT = 200

# --- Rate limits -----------------------------------------------------------

# Two different questions were being conflated here. The endpoint limit asks
# how much traffic a legitimate creator generates; upstream token capacity
# asks how much the judge can serve. An earlier version lowered this to 6 to
# match measured Groq throughput, which penalised legitimate users for a
# provider's free-tier quota. Capacity is handled by graceful degradation
# instead: a judge that 429s upstream yields a single-signal run, which the
# completeness multiplier caps below the verdict gate.
SUBMIT_RATE_LIMITS = "10 per minute;100 per hour"

# flask-limiter 3.x wants this explicitly. In-memory means counters reset on
# restart and are per-process, which is fine for a single dev server and is
# not fine behind more than one worker.
RATELIMIT_STORAGE_URI = "memory://"
LOG_RATE_LIMITS = "30 per minute"

# flask-limiter only populates RateLimitExceeded.retry_after and emits the
# Retry-After header when this is on. Section 6 requires that header on 429.
RATELIMIT_HEADERS_ENABLED = True

# --- LLM judge (planning.md section 1, signal 2) ---------------------------

JUDGE_MODEL = "openai/gpt-oss-120b"
JUDGE_TEMPERATURE = 0.0  # section 1: pinned to 0 to narrow run-to-run variance
JUDGE_MAX_TOKENS = 2000  # gpt-oss emits reasoning tokens; a low cap truncates
                         # the JSON and the request fails validation server-side
JUDGE_TIMEOUT_SECONDS = 25.0
JUDGE_MAX_RETRIES = 3  # Groq free tier is 8000 TPM; 429s are common and recoverable

JUDGE_RUBRIC_CATEGORIES = (
    "hedging_symmetry",
    "indexical_specificity",
    "structural_signposting",
    "register_uniformity",
)

# Section 2, qualified agreement: these two measure the same underlying
# property as the stylometric signal, so agreement driven only by them is one
# signal counted twice. Consumed by the fusion engine.
JUDGE_CORRELATED_CATEGORIES = ("structural_signposting", "register_uniformity")

# --- Signal weights (planning.md section 1) --------------------------------

STYLOMETRIC_WEIGHT = 0.35
JUDGE_WEIGHT = 0.65  # unused until M4, here so the pair stays visible together

# --- Fusion and confidence (planning.md section 2) -------------------------

CONF_WEIGHT_AGREEMENT = 0.40
CONF_WEIGHT_EXTREMITY = 0.35
CONF_WEIGHT_SUFFICIENCY = 0.25

# Applied when only one signal returned a usable score.
COMPLETENESS_FULL = 1.0
COMPLETENESS_DEGRADED = 0.55

# Section 2 defines agreement as 1 - abs(s1 - s2), which is undefined with one
# signal. Worked example 5 (likelihood 0.91, confidence 0.51) is reproduced
# only by treating a lone signal as agreeing with itself. That is generous on
# its face; COMPLETENESS_DEGRADED is what actually limits the result, and the
# combination caps a single-signal run below the 0.75 verdict gate.
AGREEMENT_WHEN_SINGLE_SIGNAL = 1.0

# Qualified agreement: agreement driven only by categories that measure the
# same property as the stylometric signal is one signal counted twice.
QUALIFIED_AGREEMENT_FACTOR = 0.5

# Formality damper. UNCALIBRATED: "top quartile" in section 2 is a
# distributional claim, and with no corpus these are proxies on the normalized
# sub-scores rather than measured percentiles. Open decision 3.
FORMALITY_BURSTINESS_MIN = 0.75
FORMALITY_PUNCTUATION_MIN = 0.75
FORMALITY_CONFIDENCE_CAP = 0.70

# Verdict gates. Both must clear.
VERDICT_AI_LIKELIHOOD_MIN = 0.70
VERDICT_HUMAN_LIKELIHOOD_MAX = 0.30
VERDICT_CONFIDENCE_MIN = 0.75

# --- Stylometric sub-metric weights ----------------------------------------
# Must sum to 1.0. Asserted at import.

SUB_WEIGHT_BURSTINESS = 0.40
SUB_WEIGHT_DISCOURSE_MARKERS = 0.25
SUB_WEIGHT_PUNCTUATION_ENTROPY = 0.20
SUB_WEIGHT_PARAGRAPH_UNIFORMITY = 0.15

# --- Ramp anchors ----------------------------------------------------------
# Each sub-metric maps to [0, 1] AI-likeness via a clamped linear ramp between
# HUMAN_ANCHOR (scores 0.0) and AI_ANCHOR (scores 1.0). Note the direction
# reverses for discourse markers, where a higher raw value is more AI-like.
#
# UNCALIBRATED: only the burstiness pair is specified in planning.md section 1.
# The other three were chosen to get M3 running and carry no empirical basis.
# Open decision 1 covers replacing all eight with measured percentiles.

BURSTINESS_HUMAN_ANCHOR = 0.60  # specified in planning.md section 1
BURSTINESS_AI_ANCHOR = 0.25  # specified in planning.md section 1

DISCOURSE_HUMAN_ANCHOR = 0.0  # UNCALIBRATED, markers per 100 words
DISCOURSE_AI_ANCHOR = 2.5  # UNCALIBRATED

PUNCTUATION_HUMAN_ANCHOR = 1.60  # UNCALIBRATED, Shannon entropy in bits
PUNCTUATION_AI_ANCHOR = 0.70  # UNCALIBRATED

PARAGRAPH_HUMAN_ANCHOR = 0.50  # UNCALIBRATED, coefficient of variation
PARAGRAPH_AI_ANCHOR = 0.10  # UNCALIBRATED

# --- Measurability floors --------------------------------------------------
# Below these a sub-metric is reported unavailable rather than defaulted. A
# default would be a fabricated observation, and the renormalisation in
# stylometric.py is the honest alternative.

MIN_SENTENCES_FOR_BURSTINESS = 3
MIN_PARAGRAPHS_FOR_UNIFORMITY = 2
MIN_PUNCTUATION_MARKS_FOR_ENTROPY = 3
MIN_WORDS_FOR_DISCOURSE_DENSITY = 30

# --- Discourse markers (planning.md section 1) -----------------------------
# Matched case-insensitively on word boundaries.

DISCOURSE_MARKERS = (
    "however",
    "moreover",
    "furthermore",
    "in conclusion",
    "it is important to",
    "it's important to",
    "overall",
    "additionally",
)

# --- Punctuation classes for the entropy measure ---------------------------

PUNCTUATION_CLASSES = (".", ",", ";", ":", "?", "!", "(", ")", "-", "...")

_sub_weights = (
    SUB_WEIGHT_BURSTINESS
    + SUB_WEIGHT_DISCOURSE_MARKERS
    + SUB_WEIGHT_PUNCTUATION_ENTROPY
    + SUB_WEIGHT_PARAGRAPH_UNIFORMITY
)
assert abs(_sub_weights - 1.0) < 1e-9, f"sub-metric weights sum to {_sub_weights}"
