"""End-to-end smoke test of the running CEU portal stack."""
import io
import json
import urllib.request
import urllib.error

API = "http://localhost:8000/api"
FRONT = "http://127.0.0.1:8090"
checks = []
skipped = []


def req(method, path, token=None, body=None, raw=False, content_type="application/json"):
    url = API + path
    data = None
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if body is not None:
        if isinstance(body, (dict, list)):
            data = json.dumps(body).encode()
            headers["Content-Type"] = content_type
        else:
            data = body
            headers["Content-Type"] = content_type
    r = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(r) as resp:
        payload = resp.read()
        return resp.status, payload if raw else (json.loads(payload) if payload else None)


def upload(path, token, filename, content_bytes):
    boundary = "XBOUNDARYX"
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
        f"Content-Type: text/csv\r\n\r\n"
    ).encode() + content_bytes + f"\r\n--{boundary}--\r\n".encode()
    return req("POST", path, token, body, content_type=f"multipart/form-data; boundary={boundary}")


def check(name, ok, detail=""):
    checks.append((name, ok, detail))
    print(("PASS" if ok else "FAIL"), name, detail)


def skip(name, why):
    """Record a check that could not run on this machine's configuration.

    Kept out of `checks` so it neither passes nor fails the run, but printed
    loudly — a silently skipped check reads as a passing one, which is how a
    smoke test ends up green while covering less than it claims.
    """
    skipped.append((name, why))
    print("SKIP", name, "—", why)


# 1. Frontend serves the app
with urllib.request.urlopen(FRONT + "/") as resp:
    html = resp.read().decode()
check("frontend serves index.html", resp.status == 200 and "flutter" in html.lower())

# 2. CORS preflight from the frontend origin
r = urllib.request.Request(
    API + "/auth/login", method="OPTIONS",
    headers={"Origin": "http://127.0.0.1:8090",
             "Access-Control-Request-Method": "POST",
             "Access-Control-Request-Headers": "content-type,authorization"})
with urllib.request.urlopen(r) as resp:
    acao = resp.headers.get("access-control-allow-origin")
check("CORS preflight allows frontend origin", acao == "http://127.0.0.1:8090", f"ACAO={acao}")

# 3. Login admin
_, login = req("POST", "/auth/login", body={"email": "admin@example.com", "password": "Admin123!"})
token = login["access_token"]
check("admin login", bool(token))

# presenter cannot upload a certificate template (403) — checked later after event exists
_, plogin = req("POST", "/auth/login", body={"email": "presenter@example.com", "password": "Presenter123!"})
ptoken = plogin["access_token"]

# 4. Create event with an internal test
status, event = req("POST", "/events", token, {
    "title": "E2E Verification Lunch & Learn",
    "event_type": "lunch_and_learn",
    "event_date": "2026-06-10",
    "ceu_hours": 1,
    "presenter_name": "Dr. Demo",
    "course_instructor": "Dr. Demo",
    "test_mode": "internal",
    "test_questions": [
        {"id": "q1", "prompt": "2+2?", "choices": ["3", "4", "5", "6"], "correct_index": 1},
        {"id": "q2", "prompt": "Capital of France?", "choices": ["Rome", "Paris", "Berlin", "Madrid"], "correct_index": 1},
    ],
})
eid = event["id"]
check("create event with internal test", status == 201 and eid > 0, f"event_id={eid}")

# 5. Upload registration + attendance
status, up = upload(f"/events/{eid}/uploads/registration", token, "reg.csv",
                    b"Full Name,Email,Company\nEve Tester,eve.tester@example.com,Acme Mobility\nNo Survey,no.survey@example.com,Acme Mobility\n")
check("upload registration CSV", status == 201 and up["row_count"] == 2, f"errors={up['parse_errors']}")
status, up = upload(f"/events/{eid}/uploads/attendance", token, "att.csv",
                    b"Name,Email\nEVE TESTER,eve.tester@example.com\nNo Survey,no.survey@example.com\n")
check("upload attendance CSV", status == 201 and up["row_count"] == 2)

# 6. Public test: fetch (no answer key) and submit passing answers for both attendees
_, pub = req("GET", f"/public/tests/{event['test_token']}")
check("public test hides answer key", all("correct_index" not in q for q in pub["questions"]))
_, result = req("POST", f"/public/tests/{event['test_token']}",
                body={"full_name": "Eve Tester", "email": "eve.tester@example.com",
                      "answers": {"q1": 1, "q2": 1}})
check("public test submit scores 100 + passes", result["score"] == 100.0 and result["passed"])
_, result = req("POST", f"/public/tests/{event['test_token']}",
                body={"full_name": "No Survey", "email": "no.survey@example.com",
                      "answers": {"q1": 1, "q2": 1}})
check("second attendee passes test", result["passed"])

# 7. Survey submitted by Eve only — "No Survey" must STILL be eligible
_, _ = req("POST", f"/public/surveys/{event['survey_token']}",
           body={"full_name": "Eve Tester", "email": "eve.tester@example.com",
                 "answers": {"liked": "Great pacing and real examples", "improve": "More time for questions", "learned": "New transfer technique"}})
_, rows = req("GET", f"/events/{eid}/compliance", token)
by_name = {r["full_name"]: r for r in rows}
check("attendee with survey is eligible", by_name["Eve Tester"]["eligible"], str(by_name["Eve Tester"]["eligibility_reasons"]))
check("attendee WITHOUT survey is still eligible", by_name["No Survey"]["eligible"], str(by_name["No Survey"]["eligibility_reasons"]))

# 8. Approve both, generate + download certificate
ids = [by_name["Eve Tester"]["id"], by_name["No Survey"]["id"]]
status, rows = req("POST", f"/events/{eid}/compliance/approve", token, {"event_attendee_ids": ids, "approved": True})
check("approve attendees", all(r["approved"] for r in rows))
status, cert = req("POST", f"/events/{eid}/certificates/{ids[0]}/generate", token)
check("generate certificate", status == 200 and cert["certificate_number"], cert["certificate_number"])
status, pdf = req("GET", f"/events/{eid}/certificates/{cert['id']}/download", token, raw=True)
check("download certificate PDF", status == 200 and pdf[:4] == b"%PDF", f"{len(pdf)} bytes")

# 9. Send certificate email.
#
# Delivery depends on how this machine is configured, not on the code under
# test: with EMAIL_DELIVERY_MODE=log it always succeeds, but pointed at a real
# provider the seeded @example.com recipients are rejected outright (Resend
# refuses them by policy), and the API correctly answers 502. Treat that as a
# skip rather than a failure, so a developer with real SMTP credentials in
# .env still gets to run the remaining twenty checks.
delivery_configured = True
try:
    status, sent = req("POST", f"/events/{eid}/certificates/{ids[0]}/send", token)
    check("send certificate email", status == 200 and sent["sent_at"])
except urllib.error.HTTPError as e:
    if e.code == 502:
        delivery_configured = False
        skip(
            "send certificate email",
            "mail provider rejected the seeded @example.com recipient — "
            "set EMAIL_DELIVERY_MODE=log in backend/.env to exercise this path",
        )
    else:
        raise

# 10. Distribute test/survey invites
if delivery_configured:
    status, dist = req("POST", f"/events/{eid}/distribute", token)
    check("distribute invites", dist["sent"] == 2 and not dist["failed"], str(dist))
else:
    # The report still has to come back itemized even when every send fails —
    # that is the shape the UI renders its retry list from.
    status, dist = req("POST", f"/events/{eid}/distribute", token)
    check(
        "distribute reports per-recipient failures",
        dist["failed"] == 2 and len(dist["recipients"]) == 2
        and all(r["reason"] for r in dist["recipients"]),
        f"{dist['failed']} failed, each with a reason",
    )

# 11. QR codes
status, png = req("GET", f"/events/{eid}/test-qr", token, raw=True)
check("test QR PNG", png[:8] == b"\x89PNG\r\n\x1a\n")
status, png = req("GET", f"/events/{eid}/survey-qr", token, raw=True)
check("survey QR PNG", png[:8] == b"\x89PNG\r\n\x1a\n")

# 12. Reports, charts, insights, audit
status, csv_data = req("GET", "/reports/annual/2026?eligibility=eligible", token, raw=True)
check("annual report CSV includes attendees", b"Eve Tester" in csv_data and b"No Survey" in csv_data)
_, charts = req("GET", "/dashboard/charts", token)
check("dashboard charts", any(b["value"] > 0 for b in charts["score_distribution"]))
_, summary = req("GET", f"/events/{eid}/summary", token)
check("event summary", summary["test_passed"] == 2 and summary["eligible"] == 2, str(summary))
_, insights = req("GET", "/survey-insights", token)
check("survey insights", insights["response_count"] >= 1)
_, logs = req("GET", "/audit-logs?limit=300", token)
check("audit log captured workflow", len(logs) >= 8, f"{len(logs)} entries")

# 13. Permission checks: presenter blocked from admin-only actions
try:
    upload(f"/events/{eid}/certificates/template", ptoken, "t.pdf", b"%PDF-1.4 fake")
    check("presenter blocked from template upload", False, "expected 403/404")
except urllib.error.HTTPError as e:
    check("presenter blocked from template upload", e.code in (403, 404), f"HTTP {e.code}")
try:
    req("GET", "/audit-logs", ptoken)
    check("presenter blocked from audit logs", False, "expected 403")
except urllib.error.HTTPError as e:
    check("presenter blocked from audit logs", e.code == 403, f"HTTP {e.code}")
try:
    req("GET", "/events", token="bogus-token")
    check("bogus token rejected", False)
except urllib.error.HTTPError as e:
    check("bogus token rejected", e.code in (401, 403), f"HTTP {e.code}")

failed = [c for c in checks if not c[1]]
print(f"\n{len(checks) - len(failed)}/{len(checks)} checks passed")
if skipped:
    # Repeated at the end because the SKIP line scrolled past twenty checks
    # ago, and "21/21 passed" on its own would overstate what just ran.
    print(f"{len(skipped)} skipped on this machine's configuration:")
    for name, why in skipped:
        print(f"  - {name}: {why}")
raise SystemExit(1 if failed else 0)
