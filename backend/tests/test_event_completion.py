"""When an event is finished, and when a later file makes it unfinished again.

An event flips to "completed" once every approved attendee's certificate has
reached them. The bug these pin: *any* upload afterwards flipped it straight
back to "review" — including a re-upload that changed nothing — so an event the
compliance owner had signed off reappeared in the work queue looking undone,
with no record of what reopened it.
"""
from helpers_api import compliance_rows_by_name, create_event, upload_csv


def _event(client, headers, event_id):
    return client.get(f"/api/events/{event_id}", headers=headers).json()


def _finished_event(client, admin):
    """An event with one attendee whose certificate has been issued and sent."""
    event = create_event(client, admin.headers, test_required=False)
    response = client.post(
        f"/api/events/{event['id']}/certificates/issue",
        headers=admin.headers,
        json={"full_name": "Solo Attendee", "email": "solo@example.com", "send_email": True},
    )
    assert response.status_code == 201, response.text
    assert _event(client, admin.headers, event["id"])["status"] == "completed"
    return event


class TestAutoCompletion:
    def test_sending_the_last_certificate_completes_the_event(self, client, admin):
        event = create_event(client, admin.headers, test_required=False)
        assert _event(client, admin.headers, event["id"])["status"] == "draft"
        _finished = client.post(
            f"/api/events/{event['id']}/certificates/issue",
            headers=admin.headers,
            json={"full_name": "Ima Learner", "email": "ima@example.com", "send_email": True},
        )
        assert _finished.status_code == 201, _finished.text
        assert _event(client, admin.headers, event["id"])["status"] == "completed"

    def test_a_generated_but_unsent_certificate_does_not_complete_it(self, client, admin):
        event = create_event(client, admin.headers, test_required=False)
        client.post(
            f"/api/events/{event['id']}/certificates/issue",
            headers=admin.headers,
            json={"full_name": "Not Sent", "email": "notsent@example.com", "send_email": False},
        )
        # The holder does not have it, so the event is not finished.
        assert _event(client, admin.headers, event["id"])["status"] != "completed"


class TestUploadAfterCompletion:
    def test_a_reupload_that_adds_nobody_leaves_it_completed(self, client, admin):
        event = _finished_event(client, admin)
        # The same person, already holding their certificate. Nothing is owed,
        # so nothing should drag the event back into the queue.
        response = upload_csv(
            client,
            admin.headers,
            event["id"],
            "attendance",
            "Name,Email\nSolo Attendee,solo@example.com\n",
        )
        assert response.status_code == 201, response.text
        assert _event(client, admin.headers, event["id"])["status"] == "completed"

    def test_a_late_sign_in_sheet_with_a_new_person_reopens_it(self, client, admin):
        event = _finished_event(client, admin)
        response = upload_csv(
            client,
            admin.headers,
            event["id"],
            "attendance",
            "Name,Email\nSolo Attendee,solo@example.com\nLate Arrival,late@example.com\n",
        )
        assert response.status_code == 201, response.text
        # Somebody new earned a certificate and nobody has ruled on them yet,
        # so the event genuinely is not finished.
        assert _event(client, admin.headers, event["id"])["status"] == "review"
        rows = compliance_rows_by_name(client, admin.headers, event["id"])
        assert rows["Late Arrival"]["approved"] is False

    def test_reopening_is_audited_so_the_status_change_is_traceable(self, client, admin):
        event = _finished_event(client, admin)
        upload_csv(
            client,
            admin.headers,
            event["id"],
            "attendance",
            "Name,Email\nSolo Attendee,solo@example.com\nLate Arrival,late@example.com\n",
        )
        logs = client.get("/api/audit-logs?limit=100", headers=admin.headers).json()
        reopened = [entry for entry in logs if entry["action"] == "event.reopened"]
        assert reopened, "reopening a completed event must leave a trail"
        details = reopened[0]["details"]
        assert details["trigger"] == "upload_after_completion"
        # Names the file, so "why did this reopen" is answerable months later.
        assert details["file_type"] == "attendance"
        assert details["filename"]

    def test_a_quiet_reupload_writes_no_reopen_entry(self, client, admin):
        event = _finished_event(client, admin)
        upload_csv(
            client,
            admin.headers,
            event["id"],
            "attendance",
            "Name,Email\nSolo Attendee,solo@example.com\n",
        )
        logs = client.get("/api/audit-logs?limit=100", headers=admin.headers).json()
        assert not [entry for entry in logs if entry["action"] == "event.reopened"]

    def test_an_unfinished_event_still_moves_to_review_on_upload(self, client, admin):
        # The ordinary path is untouched: a draft event picking up its first
        # file is under review, exactly as before.
        event = create_event(client, admin.headers, test_required=False)
        upload_csv(
            client,
            admin.headers,
            event["id"],
            "attendance",
            "Name,Email\nFirst Person,first@example.com\n",
        )
        assert _event(client, admin.headers, event["id"])["status"] == "review"
