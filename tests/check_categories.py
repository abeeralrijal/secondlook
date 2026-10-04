"""Are all three label categories reachable with realistic input?

The confidence model is only useful if it distinguishes cases. A system that
returns uncertain for everything is as uninformative as one that returns a
verdict for everything.
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
    ("polished uniform (long)", samples.LONG_AI,          "ai"),
    ("casual irregular (long)", samples.LONG_HUMAN,       "human"),
    ("formal, non-native",      samples.FORMAL_NONNATIVE, None),
    ("canonical short text",    samples.SHORT_210,        None),
]

print(f"  {'input':<26} {'chars':>6} {'styl':>6} {'judge':>6} {'fused':>7} {'conf':>7}  verdict")
print("  " + "-" * 78)
seen, results = set(), []
for label, text, _ in CASES:
    s1 = stylometric_signal(text)
    s2 = judge_signal(text)
    r = fuse(s1, s2, len(text))
    seen.add(r["verdict"])
    results.append((label, r, s1, s2))
    print(f"  {label:<26} {len(text):>6} {str(s1['score']):>6} {str(s2['score']):>6} "
          f"{str(r['ai_likelihood']):>7} {str(r['confidence']):>7}  {r['verdict']}")
    time.sleep(10)

print("\n=== Checks ===")
likelihoods = [r["ai_likelihood"] for _, r, _, _ in results if r["ai_likelihood"] is not None]
spread = max(likelihoods) - min(likelihoods)


def check(name, ok, note=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name:<46} {note}")


check("score varies across clearly different inputs", spread > 0.4,
      f"likelihood range {min(likelihoods):.3f} to {max(likelihoods):.3f}, spread {spread:.3f}")
check("at least 3 distinct categories reached", len(seen) >= 3,
      f"reached: {sorted(seen)}")
check("polished uniform text reads as AI", results[0][1]["verdict"] == "ai",
      f"{results[0][1]['verdict']} at confidence {results[0][1]['confidence']}")
check("casual irregular text reads as human", results[1][1]["verdict"] == "human",
      f"{results[1][1]['verdict']} at confidence {results[1][1]['confidence']}")
