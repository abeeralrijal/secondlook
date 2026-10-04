"""M4 fusion verification (planning.md section 11).

The five worked examples in section 2 are the test cases, with the tabulated
values as expected results. These were written into the spec before the code
existed, so they test spec fidelity rather than self-consistency.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fusion import fuse
import config

TOL = 0.015  # the spec table rounds to two decimals


def sig(name, score, status="ok", **kw):
    d = {"name": name, "score": score, "status": status, "weight": 0.0, "reasons": []}
    d.update(kw)
    return d


def flat_components(burst=0.5, punct=0.5):
    """Sub-metrics that do not trigger the formality damper unless asked."""
    return {
        "burstiness": {"available": True, "score": burst, "weight": 0.40},
        "punctuation_entropy": {"available": True, "score": punct, "weight": 0.20},
    }


# label, s1, s2, chars, expected likelihood/agreement/extremity/sufficiency/confidence/verdict
CASES = [
    ("both agree, AI, long",    0.88, 0.93, 2000, 0.91, 0.95, 0.82, 1.00, 0.92, "ai"),
    ("signals disagree",        0.85, 0.18, 2000, 0.41, 0.33, 0.18, 1.00, 0.45, "uncertain"),
    ("both agree, human, long", 0.12, 0.08, 2000, 0.09, 0.96, 0.82, 1.00, 0.92, "human"),
    ("strong agree, short",     0.90, 0.88,  170, 0.89, 0.98, 0.78, 0.05, 0.68, "uncertain"),
    ("judge unavailable",       0.91, None, 2000, 0.91, None, 0.82, 1.00, 0.51, "uncertain"),
]

print("\n=== Section 2 worked examples ===")
print(f"  {'case':<24} {'field':<12} {'spec':>7} {'actual':>8}  result")
failures = 0

for label, s1, s2, chars, e_like, e_agree, e_ext, e_suf, e_conf, e_verdict in CASES:
    stylo = sig("stylometric", s1, components=flat_components())
    judge = (sig("llm_judge", s2, categories_fired=[]) if s2 is not None
             else sig("llm_judge", None, status="failed"))
    r = fuse(stylo, judge, chars)
    c = r["components"]

    checks = [
        ("ai_likelihood", e_like, r["ai_likelihood"]),
        ("agreement", e_agree, c.get("agreement")),
        ("extremity", e_ext, c.get("extremity")),
        ("sufficiency", e_suf, c.get("sufficiency")),
        ("confidence", e_conf, r["confidence"]),
    ]
    first = True
    for field, expected, actual in checks:
        if expected is None:
            continue
        ok = actual is not None and abs(actual - expected) <= TOL
        failures += 0 if ok else 1
        print(f"  {(label if first else ''):<24} {field:<12} {expected:>7.2f} {actual:>8.4f}  "
              f"{'ok' if ok else 'MISMATCH'}")
        first = False
    v_ok = r["verdict"] == e_verdict
    failures += 0 if v_ok else 1
    print(f"  {'':<24} {'verdict':<12} {e_verdict:>7} {r['verdict']:>8}  "
          f"{'ok' if v_ok else 'MISMATCH'}")
    print()

print("=== Damper and gate behaviour ===")


def check(name, ok, note=""):
    global failures
    failures += 0 if ok else 1
    print(f"  {'PASS' if ok else 'FAIL'}  {name:<46} {note}")


# Qualified agreement: judge fired only correlated categories.
corr = fuse(sig("stylometric", 0.90, components=flat_components()),
            sig("llm_judge", 0.92, categories_fired=["structural_signposting",
                                                     "register_uniformity"]), 2000)
indep = fuse(sig("stylometric", 0.90, components=flat_components()),
             sig("llm_judge", 0.92, categories_fired=["indexical_specificity"]), 2000)
check("qualified agreement halves agreement",
      abs(corr["components"]["agreement"] - 0.5 * indep["components"]["agreement"]) < 1e-6,
      f"{corr['components']['agreement']} vs {indep['components']['agreement']}")
check("qualified agreement is recorded",
      "qualified_agreement" in corr["rules_fired"])
check("independent category does not halve",
      "qualified_agreement" not in indep["rules_fired"])

# Formality damper.
formal = fuse(sig("stylometric", 0.95, components=flat_components(burst=0.9, punct=0.85)),
              sig("llm_judge", 0.95, categories_fired=["indexical_specificity"]), 2000)
check("formality damper caps confidence at 0.70",
      formal["confidence"] <= config.FORMALITY_CONFIDENCE_CAP + 1e-9,
      f"confidence {formal['confidence']}")
check("damper forces uncertain despite agreement",
      formal["verdict"] == "uncertain",
      f"likelihood {formal['ai_likelihood']}, verdict {formal['verdict']}")
check("damper is recorded", "formality_damper" in formal["rules_fired"])

# The claim the labels in section 3 depend on.
worst = max(
    fuse(sig("stylometric", s, components=flat_components()),
         sig("llm_judge", None, status="failed"), 20000)["confidence"]
    for s in (0.0, 0.5, 1.0)
)
check("single signal cannot reach the 0.75 gate", worst < config.VERDICT_CONFIDENCE_MIN,
      f"max achievable {worst}")

both_failed = fuse(sig("stylometric", None, status="failed"),
                   sig("llm_judge", None, status="failed"), 2000)
check("both failed returns uncertain, not an error",
      both_failed["verdict"] == "uncertain" and both_failed["confidence"] == 0.0,
      f"verdict {both_failed['verdict']}, confidence {both_failed['confidence']}, rules {both_failed['rules_fired']}")

# The 0.51 vs 0.95 distinction the brief asks for.
low = fuse(sig("stylometric", 0.52, components=flat_components()),
           sig("llm_judge", 0.50, categories_fired=[]), 2000)
high = fuse(sig("stylometric", 0.96, components=flat_components()),
            sig("llm_judge", 0.97, categories_fired=["indexical_specificity"]), 2000)
check("mid-scale agreement stays uncertain", low["verdict"] == "uncertain",
      f"likelihood {low['ai_likelihood']}, confidence {low['confidence']}")
check("decisive agreement reaches ai", high["verdict"] == "ai",
      f"likelihood {high['ai_likelihood']}, confidence {high['confidence']}")

print(f"\n=== {'ALL CHECKS PASS' if failures == 0 else str(failures) + ' MISMATCHES'} ===")
sys.exit(1 if failures else 0)
