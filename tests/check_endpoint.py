"""M3 endpoint verification (planning.md section 11)."""

import sys, os, json, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from audit import AuditLog
from store import ContentStore
import tempfile


def fake_judge(text):
    """Deterministic stand-in so endpoint tests spend no tokens."""
    return {"name": "llm_judge", "score": 0.8, "weight": 0.65, "status": "ok",
            "reasons": ["stub"], "categories_fired": ["indexical_specificity"],
            "evidence": []}

GOOD = (
    "Remote work has fundamentally transformed the modern workplace in recent years. "
    "Organizations have adapted their policies to accommodate distributed teams. "
    "However, this transition has presented a number of distinct challenges. "
    "Communication barriers can emerge when teams are not physically co-located. "
    "Additionally, maintaining company culture requires deliberate and sustained effort."
)

app = create_app(ContentStore(), AuditLog(tempfile.mktemp(suffix=".jsonl")), judge=fake_judge)
app.config["TESTING"] = True
c = app.test_client()


def check(name, expected_status, expected_code=None, **kw):
    r = c.post("/submit", json=kw.get("json"), headers=kw.get("headers"))
    body = r.get_json()
    code = (body or {}).get("error", {}).get("code")
    ok = r.status_code == expected_status and (expected_code is None or code == expected_code)
    print(f"  {'PASS' if ok else 'FAIL'}  {name:<34} -> {r.status_code} {code or ''}")
    return r, body


print("\n=== Error paths (section 6 contract) ===")
check("no body", 400, "INVALID_TYPE", json=None)
check("missing text", 400, "MISSING_FIELD", json={"creator_id": "c1"})
check("text not a string", 400, "INVALID_TYPE", json={"text": 12345})
check("text too short", 400, "TEXT_TOO_SHORT", json={"text": "tiny"})
check("text too long", 400, "TEXT_TOO_LONG", json={"text": "word " * 5000})
check("bad content_type", 400, "INVALID_CONTENT_TYPE", json={"text": GOOD, "content_type": "novel"})

print("\n=== Success path ===")
r, body = check("valid submission", 200, None, json={"text": GOOD, "content_type": "blog_post"}, headers={"X-API-Key": "k1"})

expected_keys = {
    "content_id", "status", "attribution", "ai_likelihood", "confidence",
    "label", "signals", "analyzed_at", "ruleset_version",
    "confidence_components", "rules_fired",
}
missing = expected_keys - set(body or {})
print(f"  {'PASS' if not missing else 'FAIL'}  contract keys present            -> missing={missing or 'none'}")

sig = body["signals"][0]
sig_keys = {"name", "score", "weight", "status", "reasons"}
print(f"  {'PASS' if set(sig) == sig_keys else 'FAIL'}  signal shape matches section 1   -> {sorted(sig)}")
print(f"  {'PASS' if isinstance(sig['score'], float) and 0 <= sig['score'] <= 1 else 'FAIL'}"
      f"  score is a float in [0,1]        -> {sig['score']} ({type(sig['score']).__name__})")
print(f"  {'PASS' if 'components' not in sig else 'FAIL'}  sub-metrics not leaked to client")
print(f"  {'PASS' if isinstance(body['confidence'], float) else 'FAIL'}  confidence is a real number        -> {body['confidence']}")
print(f"  {'PASS' if len(body['signals']) == 2 else 'FAIL'}  both signals present              -> {[s['name'] for s in body['signals']]}")
print(f"  {'PASS' if 'placeholder' not in body['label'] else 'FAIL'}  label is real, not a placeholder  -> {body['label']['variant']}")
print(f"  {'PASS' if body['label']['variant'] == 'uncertain' else 'FAIL'}  label variant matches verdict     -> {body['label']['headline']}")
print(f"  {'PASS' if body['attribution']['result'] in ('ai','human','uncertain') else 'FAIL'}  attribution is a spec verdict     -> {body['attribution']['result']}")
print(f"  {'PASS' if body['attribution']['basis'] == 'both_signals' else 'FAIL'}  attribution states its basis      -> {body['attribution']['basis']}")

CANON = ("The sun dipped below the horizon, painting the sky in hues of amber and rose. "
         "I sat on the porch, coffee in hand, watching the neighborhood slowly go quiet.")
# Fresh bucket: validation failures above already consumed quota, and
# flask-limiter counts a request before the handler decides it is a 400.
r2 = c.post("/submit", json={"text": CANON, "creator_id": "test-user-1"},
            headers={"X-API-Key": "canonical-check"})
b2 = r2.get_json()
print(f"  {'PASS' if r2.status_code == 200 else 'FAIL'}  canonical 156-char text accepted -> {r2.status_code}")
print(f"  {'PASS' if b2.get('content_id') else 'FAIL'}  canonical returns a content_id   -> {b2.get('content_id', '')[:8]}...")

print("\n=== Rate limiting (10/min) ===")
c2 = app.test_client()
hdr = {"X-API-Key": "burst-key"}
codes = [c2.post("/submit", json={"text": GOOD}, headers=hdr).status_code for _ in range(12)]
first_429 = codes.index(429) + 1 if 429 in codes else None
print(f"  {'PASS' if first_429 == 11 else 'FAIL'}  11th request limited (10/min)    -> first 429 at #{first_429}")
r = c2.post("/submit", json={"text": GOOD}, headers=hdr)
print(f"  {'PASS' if r.headers.get('Retry-After') else 'FAIL'}  Retry-After header present       -> {r.headers.get('Retry-After')}")
print(f"  {'PASS' if r.get_json().get('error', {}).get('code') == 'RATE_LIMITED' else 'FAIL'}  429 uses the error envelope")

print("\n=== Bucket isolation ===")
r = c2.post("/submit", json={"text": GOOD}, headers={"X-API-Key": "different-key"})
print(f"  {'PASS' if r.status_code == 200 else 'FAIL'}  separate API key unaffected      -> {r.status_code}")

print("\n=== Health ===")
r = c.get("/health")
print(f"  {'PASS' if r.status_code == 200 else 'FAIL'}  /health exempt from limits       -> {r.status_code} {r.get_json()}")
