"""Calibration against four deliberately chosen inputs.

Each case carries a stated expectation written before the run. Both signal
scores are printed separately so a mismatch can be traced to one signal.
"""

import sys, os, time, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

import samples
from fusion import fuse
from signals.judge import judge_signal
from signals.stylometric import stylometric_signal

CASES = [
    ("clearly AI",        samples.BRIEF_AI,           "high",     lambda L: L >= 0.70),
    ("clearly human",     samples.BRIEF_HUMAN,        "low",      lambda L: L <= 0.30),
    ("formal human",      samples.BRIEF_FORMAL_HUMAN, "mid-high", lambda L: 0.40 <= L <= 0.80),
    ("lightly edited AI", samples.BRIEF_EDITED_AI,    "mid",      lambda L: 0.30 <= L <= 0.70),
]

results = []
for label, text, expectation, matches in CASES:
    s1 = stylometric_signal(text)
    s2 = judge_signal(text)
    r = fuse(s1, s2, len(text))
    ok = r["ai_likelihood"] is not None and matches(r["ai_likelihood"])
    results.append((label, text, expectation, s1, s2, r, ok))

    print(f"\n{'=' * 78}")
    print(f"{label.upper()}   ({len(text)} chars)   expected: {expectation}")
    print(f"{'=' * 78}")
    print(f"  signal 1  stylometric : {s1['score']}   (weight {s1['weight']})")
    for k, v in sorted((s1.get("components") or {}).items()):
        if v.get("available"):
            print(f"              {k:<22} raw={v['raw']:<9} score={v['score']}")
        else:
            print(f"              {k:<22} unavailable: {v['why']}")
    print(f"  signal 2  llm_judge   : {s2['score']}   fired={s2.get('categories_fired') or '-'}")
    for e in (s2.get("evidence") or [])[:2]:
        print(f"              {e['category']}: \"{e['quote'][:58]}\"")
    c = r["components"]
    print(f"  fused likelihood      : {r['ai_likelihood']}   "
          f"(0.35*{s1['score']} + 0.65*{s2['score']})")
    print(f"  confidence            : {r['confidence']}   "
          f"agree={c['agreement']} extrem={c['extremity']} suffic={c['sufficiency']}")
    print(f"  VERDICT               : {r['verdict']}   rules={r['rules_fired'] or '-'}")
    print(f"  matches intuition     : {'YES' if ok else 'NO'}")
    time.sleep(10)

print(f"\n{'=' * 78}")
print("SUMMARY")
print(f"{'=' * 78}")
print(f"  {'case':<20} {'expected':<10} {'styl':>6} {'judge':>6} {'fused':>7} {'verdict':>10}  match")
for label, _, exp, s1, s2, r, ok in results:
    print(f"  {label:<20} {exp:<10} {str(s1['score']):>6} {str(s2['score']):>6} "
          f"{str(r['ai_likelihood']):>7} {r['verdict']:>10}  {'YES' if ok else 'NO'}")

n_ok = sum(1 for *_, ok in results if ok)
print(f"\n  likelihood matches intuition: {n_ok}/4")
verdicts = {r["verdict"] for *_, r, _ in results}
print(f"  distinct verdicts reached:    {sorted(verdicts)}")
