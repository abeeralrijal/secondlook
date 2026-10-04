"""Where the two signals agree and where they split.

Runs both signals on the same inputs. Disagreement is the interesting part:
it says what each signal sees that the other cannot, and it is the quantity
the confidence model leans on hardest.

Paced at 10s between judge calls to stay under the 8000 TPM free tier limit.
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
    ("ai_1",        samples.AI_LIKE[0],      "ai"),
    ("ai_2",        samples.AI_LIKE[1],      "ai"),
    ("ai_3",        samples.AI_LIKE[2],      "ai"),
    ("human_1",     samples.HUMAN_LIKE[0],   "human"),
    ("human_2",     samples.HUMAN_LIKE[1],   "human"),
    ("human_3",     samples.HUMAN_LIKE[2],   "human"),
    ("sonnet",      samples.SONNET,          "human"),
    ("formal_nonnative", samples.FORMAL_NONNATIVE, "human"),
    ("technical_doc",    samples.TECHNICAL_DOC,    "human"),
    ("roughened_ai",     samples.ROUGHENED_AI,     "ai"),
]

rows = []
print(f"  {'case':<18} {'truth':<6} {'styl':>6} {'judge':>6} {'gap':>6} {'fused':>6} {'conf':>6}  verdict")
print("  " + "-" * 74)

for label, text, truth in CASES:
    s1 = stylometric_signal(text)
    s2 = judge_signal(text)
    r = fuse(s1, s2, len(text))
    gap = (abs(s1["score"] - s2["score"])
           if s1["score"] is not None and s2["score"] is not None else None)
    rows.append((label, truth, s1, s2, gap, r))
    print(f"  {label:<18} {truth:<6} {str(s1['score']):>6} {str(s2['score']):>6} "
          f"{(f'{gap:.3f}' if gap is not None else '   -'):>6} "
          f"{str(r['ai_likelihood']):>6} {str(r['confidence']):>6}  {r['verdict']}")
    time.sleep(10)

print("\n=== Where they diverge ===")
scored = [r for r in rows if r[4] is not None]
scored.sort(key=lambda r: -r[4])
for label, truth, s1, s2, gap, r in scored[:4]:
    leans = "stylometer says AI, judge says human" if s1["score"] > s2["score"] \
            else "judge says AI, stylometer says human"
    print(f"\n  {label} (truth: {truth}, gap {gap:.3f}) - {leans}")
    print(f"    stylometer: {s1['reasons'][0] if s1['reasons'] else '-'}")
    print(f"    judge:      {s2['reasons'][0] if s2['reasons'] else '-'}")
    print(f"    fired:      {s2.get('categories_fired') or '-'}")

print("\n=== Per-signal accuracy, treating 0.5 as the split ===")
for name, idx in (("stylometric", 2), ("llm_judge", 3)):
    hits = sum(1 for _, truth, s1, s2, _, _ in rows
               if (s1, s2)[idx - 2]["score"] is not None
               and (((s1, s2)[idx - 2]["score"] > 0.5) == (truth == "ai")))
    n = sum(1 for _, _, s1, s2, _, _ in rows if (s1, s2)[idx - 2]["score"] is not None)
    print(f"  {name:<14} {hits}/{n} correct")

agree = sum(1 for r in scored if r[4] < 0.25)
print(f"\n  signals within 0.25 of each other: {agree}/{len(scored)}")
print(f"  mean gap: {sum(r[4] for r in scored) / len(scored):.3f}")

print("\n=== Section 5 predictions ===")


def pred(name, label, holds, detail):
    print(f"  {'HOLDS' if holds else 'FALSIFIED':<10} {name:<24} {detail}")


by = {r[0]: r for r in rows}
f = by["formal_nonnative"]
pred("correlated failure", "formal_nonnative",
     f[2]["score"] > 0.5 and f[3]["score"] > 0.5,
     f"both flag AI: styl={f[2]['score']} judge={f[3]['score']}, verdict {f[5]['verdict']}")
t = by["technical_doc"]
pred("genre beats authorship", "technical_doc", t[2]["score"] > 0.5,
     f"stylometer flags human docs: styl={t[2]['score']} judge={t[3]['score']}")
g = by["roughened_ai"]
pred("trivial evasion", "roughened_ai", g[2]["score"] < 0.5,
     f"stylometer fooled: styl={g[2]['score']} judge={g[3]['score']}, verdict {g[5]['verdict']}")
