"""M5 verification (planning.md section 11).

The label check parses section 3 out of planning.md and compares rendered
strings character for character. Hand-copying spec text into code is exactly
where silent drift starts, so the spec is the fixture.
"""

import sys, os, re, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import tempfile
from app import create_app
from appeals import AppealStore
from audit import AuditLog
from labels import generate_label
from store import ContentStore

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
failures = 0


def check(name, ok, note=""):
    global failures
    failures += 0 if ok else 1
    print(f"  {'PASS' if ok else 'FAIL'}  {name:<48} {note}")


# --- 1. Label text against the spec itself -------------------------------
print("\n=== Label text parsed from planning.md section 3 ===")
spec = open(os.path.join(ROOT, "planning.md"), encoding="utf-8").read()
block = spec[spec.index("### Variant 1:"):spec.index("### Review notes")]

parsed = {}
for chunk in re.split(r"^### Variant \d+: ", block, flags=re.M)[1:]:
    variant = re.match(r"`([a-z_]+)`", chunk).group(1)
    fields = {}
    for key, field in (("Headline", "headline"), ("Body", "body"),
                       ("Confidence phrase", "confidence_phrase")):
        m = re.search(rf"\*\*{key}:\*\* (.+?)(?=\n\n|\Z)", chunk, re.S)
        fields[field] = " ".join(m.group(1).split())
    parsed[variant] = fields

check("all four variants found in spec", len(parsed) == 4, f"{sorted(parsed)}")

for variant, expected in parsed.items():
    actual = generate_label(
        {"high_confidence_ai": "ai", "high_confidence_human": "human"}.get(variant, "uncertain"),
        0.9,
        "under_review" if variant == "under_review" else "classified",
    )
    check(f"{variant}: variant id", actual["variant"] == variant, actual["variant"])
    for field, want in expected.items():
        got = " ".join(actual[field].split())
        check(f"{variant}: {field} matches spec exactly", got == want,
              "" if got == want else f"\n        spec: {want[:70]}\n        code: {got[:70]}")

# --- 2. Threshold mapping -------------------------------------------------
print("\n=== Verdict to variant mapping ===")
for verdict, expect in (("ai", "high_confidence_ai"), ("human", "high_confidence_human"),
                        ("uncertain", "uncertain")):
    check(f"verdict '{verdict}'", generate_label(verdict, 0.9)["variant"] == expect, expect)
check("under_review outranks an ai verdict",
      generate_label("ai", 0.95, "under_review")["variant"] == "under_review")
check("no numeric score in any label text",
      not any(re.search(r"\d", v[f])
              for v in [generate_label(x) for x in ("ai", "human", "uncertain")]
              for f in ("headline", "body", "confidence_phrase")))
check("no severity field on the label",
      "severity" not in generate_label("ai", 0.9))

# --- 3. Appeal flow -------------------------------------------------------
print("\n=== Appeal flow ===")


def fake_judge(text):
    return {"name": "llm_judge", "score": 0.95, "weight": 0.65, "status": "ok",
            "reasons": ["stub"], "categories_fired": ["indexical_specificity"],
            "evidence": [{"category": "indexical_specificity", "quote": text[:20]}]}


log_path = tempfile.mktemp(suffix=".jsonl")
app = create_app(ContentStore(), AuditLog(log_path), judge=fake_judge, appeal_store=AppealStore())
app.config["TESTING"] = True
c = app.test_client()

TEXT = ("Sustainable urban planning has become an increasingly important consideration "
        "for city governments. Municipalities must balance development pressure against "
        "environmental responsibility. Mixed-use zoning represents one widely adopted "
        "approach. By allowing residential and commercial spaces to coexist, cities can "
        "reduce commuting distances. This lowers transportation emissions across the "
        "metropolitan area. Public transit investment serves as another essential "
        "component. Well-designed networks reduce private vehicle dependency. However, "
        "such projects require substantial upfront capital. Green infrastructure offers "
        "a complementary strategy for urban sustainability overall.")

sub = c.post("/submit", json={"text": TEXT, "creator_id": "creator-1"},
             headers={"X-API-Key": "m5"}).get_json()
cid = sub["content_id"]
check("submission classified", sub["status"] == "classified",
      f"verdict {sub['attribution']['result']}, label {sub['label']['variant']}")
check("submit returns a real label (not a placeholder)",
      "placeholder" not in sub["label"], sub["label"]["variant"])

before = c.get(f"/content/{cid}").get_json()
check("GET /content before appeal", before["status"] == "classified",
      f"label {before['label']['variant']}")

r = c.post(f"/appeal/{cid}", json={
    "creator_reasoning": "I wrote this myself for a planning class and can share my drafts.",
    "grounds": "wrote_by_hand"}, headers={"X-API-Key": "m5"})
ap = r.get_json()
check("appeal returns 201", r.status_code == 201, str(r.status_code))
check("appeal returns an appeal_id", bool(ap.get("appeal_id")))
check("appeal status is under_review", ap.get("status") == "under_review")
check("appeal echoes the original decision",
      ap["original_decision"]["verdict"] == sub["attribution"]["result"],
      str(ap["original_decision"]))

after = c.get(f"/content/{cid}").get_json()
check("content status flipped to under_review", after["status"] == "under_review")
check("label switched to under_review variant",
      after["label"]["variant"] == "under_review", after["label"]["headline"])
check("original verdict preserved", after["verdict"] == sub["attribution"]["result"],
      f"{after['verdict']} / confidence {after['confidence']}")
check("appeal summary exposed on content", after["appeal"] is not None)
check("creator reasoning NOT on the reader endpoint",
      "reasoning" not in (after["appeal"] or {}))

print("\n=== Appeal error paths ===")
r = c.post(f"/appeal/{cid}", json={"creator_reasoning": "Same again, filed twice over."},
           headers={"X-API-Key": "m5b"})
check("second appeal rejected 409", r.status_code == 409,
      r.get_json()["error"]["code"])
r = c.post("/appeal/does-not-exist", json={"creator_reasoning": "Filing against nothing at all."},
           headers={"X-API-Key": "m5c"})
check("unknown content 404", r.status_code == 404, r.get_json()["error"]["code"])
# Validation cases need unappealed content: the handler checks for an existing
# appeal before it validates the body, so reusing `cid` would return 409 and
# the validation path would never run. That ordering is deliberate. Telling a
# creator their reasoning is too short, when the real problem is that they
# already appealed, implies that fixing the reasoning would let them refile.
def fresh(key):
    return c.post("/submit", json={"text": TEXT, "creator_id": "creator-x"},
                  headers={"X-API-Key": key}).get_json()["content_id"]


r = c.post(f"/appeal/{fresh('s-d')}", json={"creator_reasoning": "too short"},
           headers={"X-API-Key": "m5d"})
check("19-char reasoning rejected 400", r.status_code == 400,
      r.get_json()["error"]["code"])
r = c.post(f"/appeal/{fresh('s-e')}", json={}, headers={"X-API-Key": "m5e"})
check("missing reasoning rejected 400", r.status_code == 400,
      r.get_json()["error"]["code"])
r = c.post(f"/appeal/{fresh('s-f')}",
           json={"creator_reasoning": "A perfectly adequate explanation here.",
                 "grounds": "because_i_said_so"}, headers={"X-API-Key": "m5f"})
check("invalid grounds rejected 400", r.status_code == 400,
      r.get_json()["error"]["code"])
r = c.post(f"/appeal/{cid}", json={"creator_reasoning": "x"}, headers={"X-API-Key": "m5g"})
check("duplicate beats validation (409 not 400)", r.status_code == 409,
      r.get_json()["error"]["code"])

print("\n=== Audit chain ===")
entries = c.get(f"/log?content_id={cid}&order=asc").get_json()["entries"]
check("two entries for this content", len(entries) == 2,
      [e["event"] for e in entries])
dec = next((e for e in entries if e["event"] == "decision"), None)
app_e = next((e for e in entries if e["event"] == "appeal"), None)
check("decision entry logged", dec is not None)
check("appeal entry logged", app_e is not None)
check("appeal links to the decision entry",
      app_e and app_e.get("contested_decision_entry_id") == dec["entry_id"])
check("appeal entry records new_status",
      app_e and app_e.get("new_status") == "under_review")
check("decision entry kept both signal scores",
      dec and dec["stylometric_score"] is not None and dec["llm_score"] is not None,
      f"styl={dec['stylometric_score']} llm={dec['llm_score']}")
check("decision entry kept label_variant", dec and dec.get("label_variant") is not None,
      dec.get("label_variant"))
check("appeal_reasoning visible on public log",
      app_e and app_e.get("appeal_reasoning", "").startswith("I wrote this"), str(app_e.get("appeal_reasoning"))[:40])

import json
on_disk = [json.loads(l) for l in open(log_path)]
disk_appeal = next(e for e in on_disk if e["event"] == "appeal")
check("appeal_reasoning also on disk",
      disk_appeal["appeal_reasoning"].startswith("I wrote this myself"),
      disk_appeal["appeal_reasoning"][:36] + "...")

print(f"\n=== {'ALL CHECKS PASS' if failures == 0 else str(failures) + ' FAILURES'} ===")
sys.exit(1 if failures else 0)
