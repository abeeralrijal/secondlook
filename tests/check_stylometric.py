"""M3 verification table (planning.md section 11).

Exercises the signal in isolation, before it is wired into the endpoint.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from samples import AI_LIKE, HUMAN_LIKE, SONNET, SHORT_210, NO_TERMINAL
from signals.stylometric import stylometric_signal

def show(label, text):
    r = stylometric_signal(text)
    avail = sum(1 for c in r["components"].values() if c["available"])
    print(f"  {label:<22} score={str(r['score']):<7} status={r['status']:<7} submetrics={avail}/4")
    return r


print("\n=== AI-like paragraphs ===")
ai_scores = [show(f"ai_{i+1}", t)["score"] for i, t in enumerate(AI_LIKE)]

print("\n=== Human informal paragraphs ===")
hu_scores = [show(f"human_{i+1}", t)["score"] for i, t in enumerate(HUMAN_LIKE)]

print("\n=== Edge cases ===")
sonnet = show("sonnet", SONNET)
short = show("210_chars", SHORT_210)
noterm = show("no_terminal_punct", NO_TERMINAL)

print("\n=== Checks ===")
ai_mean, hu_mean = sum(ai_scores) / 3, sum(hu_scores) / 3
print(f"  AI mean {ai_mean:.3f} vs human mean {hu_mean:.3f}  (separation {ai_mean - hu_mean:+.3f})")
print(f"  separation positive................ {'PASS' if ai_mean > hu_mean else 'FAIL'}")
print(f"  no overlap (min AI > max human).... {'PASS' if min(ai_scores) > max(hu_scores) else 'FAIL'}")

allscores = [s for s in ai_scores + hu_scores + [sonnet['score'], short['score'], noterm['score']] if s is not None]
print(f"  all scores in [0,1]................ {'PASS' if all(0 <= s <= 1 for s in allscores) else 'FAIL'}")

runs = {stylometric_signal(HUMAN_LIKE[0])["score"] for _ in range(5)}
print(f"  deterministic over 5 runs.......... {'PASS' if len(runs) == 1 else 'FAIL'}")

# Corrected after M3 falsified the original section 5 prediction. Verse is
# line-structured, so a sonnet has too few sentences to measure burstiness at
# all; the real verse false positive comes from stanza uniformity instead.
b = sonnet["components"]["burstiness"]
d = sonnet["components"]["discourse_markers"]
p = sonnet["components"]["paragraph_uniformity"]
print(f"  sonnet: burstiness unmeasurable...  {'PASS' if not b['available'] else 'FAIL'}  ({b.get('why', '')})")
print(f"  sonnet: no discourse markers.....   {'PASS' if d['available'] and d['score'] <= 0.1 else 'FAIL'}  (score={d.get('score')})")
print(f"  sonnet: stanza uniformity flags AI  {'PASS' if p['available'] and p['score'] >= 0.7 else 'FAIL'}  (score={p.get('score')})")
print(f"  sonnet: weight reduced to {sonnet['weight']}.... {'PASS' if sonnet['weight'] < sonnet['nominal_weight'] else 'FAIL'}")

print(f"  no crash on degenerate input....... PASS")
