"""All three label variants through the live POST /submit endpoint.

Includes a pair chosen so that likelihood is similar and confidence is not,
which is what shows the label responds to confidence rather than only to
which side of the midpoint the evidence fell.
"""

import sys, os, time, json, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

import samples
from app import create_app
from appeals import AppealStore
from audit import AuditLog
from store import ContentStore
import tempfile

app = create_app(ContentStore(), AuditLog(tempfile.mktemp(suffix=".jsonl")),
                 appeal_store=AppealStore())
app.config["TESTING"] = True
c = app.test_client()

CASES = [
    ("long polished uniform", samples.LONG_AI,    "k1"),
    ("long casual irregular", samples.LONG_HUMAN, "k2"),
    ("short AI (same lean, less evidence)", samples.BRIEF_AI, "k3"),
    ("short casual",          samples.BRIEF_HUMAN, "k4"),
]

seen, rows = {}, []
for label, text, key in CASES:
    r = c.post("/submit", json={"text": text, "creator_id": "demo"},
               headers={"X-API-Key": key})
    b = r.get_json()
    rows.append((label, len(text), b))
    seen.setdefault(b["label"]["variant"], label)

    print(f"\n{'=' * 76}")
    print(f"{label}   ({len(text)} chars)")
    print(f"{'=' * 76}")
    print(f"  likelihood {b['ai_likelihood']}   confidence {b['confidence']}   "
          f"sufficiency {b['confidence_components']['sufficiency']}")
    L = b["label"]
    print(f"\n  variant            : {L['variant']}")
    print(f"  headline           : {L['headline']}")
    print(f"  body               : {L['body'][:72]}...")
    print(f"  confidence_phrase  : {L['confidence_phrase'][:72]}...")
    time.sleep(12)

print(f"\n{'=' * 76}")
print("SUMMARY")
print(f"{'=' * 76}")
print(f"  {'input':<38} {'likeli':>7} {'conf':>6}  variant")
for label, n, b in rows:
    print(f"  {label:<38} {b['ai_likelihood']:>7} {b['confidence']:>6}  {b['label']['variant']}")

print("\n=== Checks ===")
failures = 0


def check(name, ok, note=""):
    global failures
    failures += 0 if ok else 1
    print(f"  {'PASS' if ok else 'FAIL'}  {name:<48} {note}")


variants = {b["label"]["variant"] for _, _, b in rows}
check("all three variants reachable via POST /submit",
      {"high_confidence_ai", "high_confidence_human", "uncertain"} <= variants,
      f"reached {sorted(variants)}")

headlines = {b["label"]["headline"] for _, _, b in rows}
check("label text differs across submissions", len(headlines) >= 3,
      f"{len(headlines)} distinct headlines")

# The pair that isolates confidence from likelihood.
long_ai = rows[0][2]
short_ai = rows[2][2]
gap = abs(long_ai["ai_likelihood"] - short_ai["ai_likelihood"])
check("the two AI texts lean the same way", gap < 0.20,
      f"likelihoods {long_ai['ai_likelihood']} vs {short_ai['ai_likelihood']}, gap {gap:.3f}")
check("but differ in confidence",
      abs(long_ai["confidence"] - short_ai["confidence"]) > 0.15,
      f"confidence {long_ai['confidence']} vs {short_ai['confidence']}")
check("and therefore get different labels",
      long_ai["label"]["variant"] != short_ai["label"]["variant"],
      f"{long_ai['label']['variant']} vs {short_ai['label']['variant']}")

print(f"\n=== {'ALL CHECKS PASS' if failures == 0 else str(failures) + ' FAILURES'} ===")
sys.exit(1 if failures else 0)
