"""M4 judge verification (planning.md section 11).

Calls judge_signal directly. Nothing is wired into the endpoint yet.
"""

import sys, os, json, time, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from samples import AI_LIKE, HUMAN_LIKE, SONNET, INJECTION
from signals.judge import judge_signal

def run(label, text, show_evidence=False):
    t = time.time()
    r = judge_signal(text)
    elapsed = time.time() - t
    fired = ",".join(r["categories_fired"]) or "-"
    print(f"  {label:<14} score={str(r['score']):<7} verdict={str(r.get('model_verdict')):<10}"
          f" {elapsed:4.1f}s  fired=[{fired}]")
    if r["status"] != "ok":
        print(f"                 FAILED: {r['reasons'][0]} | {r.get('failure_detail')}")
    if show_evidence:
        for e in r["evidence"]:
            print(f"                 evidence {e['category']}: \"{e['quote'][:60]}\"")
    return r


print("\n=== AI-like paragraphs ===")
ai = [run(f"ai_{i+1}", t) for i, t in enumerate(AI_LIKE)]

print("\n=== Human informal paragraphs ===")
hu = [run(f"human_{i+1}", t) for i, t in enumerate(HUMAN_LIKE)]

print("\n=== Verse ===")
sonnet = run("sonnet", SONNET, show_evidence=True)

print("\n=== Prompt injection attempt ===")
inj = run("injection", INJECTION, show_evidence=True)

print("\n=== Determinism, 5 runs on the same text ===")
# HUMAN_LIKE[1] is used deliberately: HUMAN_LIKE[0] is stable and testing it
# gave false assurance. Instability here is text-dependent.
raw_runs = [judge_signal(HUMAN_LIKE[1]) for _ in range(5)]
runs = [r["score"] for r in raw_runs if r["score"] is not None]
n_failed = len(raw_runs) - len(runs)
spread = (max(runs) - min(runs)) if len(runs) > 1 else None
print(f"  scores: {[r['score'] for r in raw_runs]}")
print(f"  spread: {spread}  failed_calls: {n_failed}")
for r in raw_runs:
    if r["status"] != "ok":
        print(f"  failure detail: {r.get('failure_detail')}")

print("\n=== Checks ===")
ai_s = [r["score"] for r in ai if r["score"] is not None]
hu_s = [r["score"] for r in hu if r["score"] is not None]


def check(name, ok, note=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name:<42} {note}")


check("all calls returned status ok", all(r["status"] == "ok" for r in ai + hu + [sonnet, inj]))
check("every score in [0,1]", all(0 <= s <= 1 for s in ai_s + hu_s))
if ai_s and hu_s:
    sep = sum(ai_s) / len(ai_s) - sum(hu_s) / len(hu_s)
    check("AI mean above human mean", sep > 0, f"separation {sep:+.3f}")
    check("no overlap between sets", min(ai_s) > max(hu_s),
          f"min AI {min(ai_s):.2f} vs max human {max(hu_s):.2f}")
check("sonnet not called AI", sonnet["score"] is not None and sonnet["score"] < 0.5,
      f"score {sonnet['score']}")
check("injection did not force human verdict", inj["score"] is None or inj["score"] > 0.05,
      f"score {inj['score']}, model said {inj.get('model_verdict')}")
check("no fabricated quotes survived",
      all(r.get("fabricated_quotes", 0) == 0 for r in ai + hu + [sonnet, inj]),
      f"dropped {sum(r.get('fabricated_quotes', 0) for r in ai + hu + [sonnet, inj])} total")
check("all 5 determinism calls succeeded", n_failed == 0, f"{n_failed} failed")
check("judge stable enough for 0.65 weight", spread is not None and spread <= 0.15,
      f"spread {spread}")
