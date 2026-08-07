"""Correcting a mistyped attendee email or name (PATCH /api/attendees/{id}).

The behaviours pinned here are the ones that make this safe to expose at all:
the correction lands in the same normalized form an import produces, it re-runs
eligibility, it refuses an identity collision instead of silently merging, and
it refuses to rewrite the identity under a certificate somebody already holds.
"""
import pytest
from helpers_api import compliance_rows_by_name, create_event, upload_standard_roster

from app.models.attendee import Attendee
from app.models.certificate import Certificate


@pytest.fixture()
def event(client, admin):
    return create_event(client, admin.headers, title="Correction Flow CEU")


@pytest.fixture()
def rows(client, admin, event):
    upload_standard_roster(client, admin.headers, event["id"])
    return compliance_rows_by_name(client, admin.headers, event["id"])


def correct(client, headers, attendee_id, **payload):
    return client.patch(f"/api/attendees/{attendee_id}", json=payload, headers=headers)


def audit_actions(client, headers) -> list[dict]:
    response = client.get("/api/audit-logs", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def approve(client, headers, event_id, link_id, override=False):
    response = client.post(
        f"/api/events/{event_id}/compliance/approve",
        json={"event_attendee_ids": [link_id], "approved": True, "override": override},
        headers=headers,
    )
    assert response.status_code == 200, response.text


class TestEmailCorrection:
    def test_fixes_the_address_and_makes_the_attendee_eligible(
        self, client, admin, event, rows
    ):
        # Cara is on the roster with "cara-at-example.com": she attended and
        # passed, and the only thing blocking her certificate is the address.
        cara = rows["Cara Fields"]
        assert cara["eligible"] is False
        assert "Missing or invalid email" in cara["eligibility_reasons"]

        response = correct(
            client, admin.headers, cara["attendee_id"], email="cara.fields@example.com"
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["email"] == "cara.fields@example.com"
        assert body["changed"] == ["email"]
        assert body["events_recalculated"] == [event["id"]]
        # The point of the whole endpoint: eligibility is re-derived, without
        # anybody re-uploading a file.
        assert body["newly_eligible"] == [cara["id"]]

        after = compliance_rows_by_name(client, admin.headers, event["id"])["Cara Fields"]
        assert after["eligible"] is True
        assert after["has_valid_email"] is True
        assert after["eligibility_reasons"] == []

    def test_stored_in_the_same_normalized_form_an_import_would_produce(
        self, client, admin, db_session, event, rows
    ):
        cara_id = rows["Cara Fields"]["attendee_id"]
        # Display-name form, mixed case and padding -- exactly the shapes the
        # import path normalizes away. A correction that stored the raw text
        # would make matching and eligibility disagree with each other.
        response = correct(
            client, admin.headers, cara_id, email="  Cara Fields <CARA.Fields@Example.COM> "
        )
        assert response.status_code == 200, response.text

        attendee = db_session.get(Attendee, cara_id)
        db_session.refresh(attendee)
        assert attendee.email == "cara.fields@example.com"
        assert attendee.normalized_email == "cara.fields@example.com"

    def test_unusable_address_is_rejected(self, client, admin, rows):
        # EmailStr stops most of it; this pins that a value which survives
        # EmailStr but normalizes to nothing cannot be stored either.
        response = correct(client, admin.headers, rows["Cara Fields"]["attendee_id"], email="n/a")
        assert response.status_code == 422, response.text

    def test_restating_the_existing_address_changes_nothing(self, client, admin, rows):
        alice = rows["Alice Nguyen"]
        response = correct(
            client, admin.headers, alice["attendee_id"], email="ALICE.NGUYEN@example.com"
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["changed"] == []
        assert body["email"] == "alice.nguyen@example.com"


class TestNameCorrection:
    def test_name_is_humanized_and_the_split_fields_follow(
        self, client, admin, db_session, rows
    ):
        cara_id = rows["Cara Fields"]["attendee_id"]
        # "Last, First" is how Teams and registration exports write names; a
        # correction typed that way has to land the way an import would.
        response = correct(client, admin.headers, cara_id, full_name="Fields, Carasa")
        assert response.status_code == 200, response.text
        assert response.json()["full_name"] == "Carasa Fields"
        assert response.json()["changed"] == ["full_name"]

        attendee = db_session.get(Attendee, cara_id)
        db_session.refresh(attendee)
        assert attendee.full_name == "Carasa Fields"
        assert attendee.normalized_name == "carasa fields"
        assert attendee.first_name == "Carasa"
        assert attendee.last_name == "Fields"

    def test_email_and_name_can_be_corrected_together(self, client, admin, rows):
        response = correct(
            client,
            admin.headers,
            rows["Cara Fields"]["attendee_id"],
            full_name="Kara Fields",
            email="kara.fields@example.com",
        )
        assert response.status_code == 200, response.text
        assert sorted(response.json()["changed"]) == ["email", "full_name"]

    def test_empty_payload_is_rejected(self, client, admin, rows):
        response = correct(client, admin.headers, rows["Cara Fields"]["attendee_id"])
        assert response.status_code == 422, response.text


class TestIdentityCollision:
    def test_correcting_onto_another_attendees_address_is_refused(
        self, client, admin, db_session, rows
    ):
        cara = rows["Cara Fields"]
        response = correct(
            client, admin.headers, cara["attendee_id"], email="bob.ramos@example.com"
        )
        assert response.status_code == 409, response.text
        detail = response.json()["detail"]
        # The message has to name who it collides with and say why this is not
        # an edit, or the admin has no way to act on it.
        assert "Bob Ramos" in detail
        assert "merge" in detail.lower()

        # Nothing was written: a refused merge must not half-apply.
        attendee = db_session.get(Attendee, cara["attendee_id"])
        db_session.refresh(attendee)
        assert attendee.email == "cara-at-example.com"

    def test_collision_is_detected_in_normalized_form(self, client, admin, rows):
        # Different case and a display name, same identity.
        response = correct(
            client,
            admin.headers,
            rows["Cara Fields"]["attendee_id"],
            email="Bob Ramos <BOB.RAMOS@EXAMPLE.COM>",
        )
        assert response.status_code == 409, response.text

    def test_blocked_collision_is_audited(self, client, admin, rows):
        correct(client, admin.headers, rows["Cara Fields"]["attendee_id"], email="bob.ramos@example.com")
        blocked = [
            entry
            for entry in audit_actions(client, admin.headers)
            if entry["action"] == "attendee.correction_blocked"
        ]
        assert len(blocked) == 1
        assert blocked[0]["details"]["reason"] == "email_belongs_to_another_attendee"
        assert blocked[0]["actor_id"] == admin.id


class TestIssuedCertificateGuard:
    def test_delivered_certificate_blocks_the_correction(
        self, client, admin, db_session, event, rows
    ):
        alice = rows["Alice Nguyen"]
        approve(client, admin.headers, event["id"], alice["id"])
        assert client.post(
            f"/api/events/{event['id']}/certificates/{alice['id']}/generate",
            headers=admin.headers,
        ).status_code == 200
        assert client.post(
            f"/api/events/{event['id']}/certificates/{alice['id']}/send", headers=admin.headers
        ).status_code == 200

        response = correct(
            client, admin.headers, alice["attendee_id"], full_name="Alyce Nguyen"
        )
        assert response.status_code == 409, response.text
        detail = response.json()["detail"]
        assert "revoke" in detail.lower()

        attendee = db_session.get(Attendee, alice["attendee_id"])
        db_session.refresh(attendee)
        assert attendee.full_name == "Alice Nguyen"

    def test_delivered_certificate_also_blocks_an_email_correction(
        self, client, admin, event, rows
    ):
        alice = rows["Alice Nguyen"]
        approve(client, admin.headers, event["id"], alice["id"])
        client.post(
            f"/api/events/{event['id']}/certificates/{alice['id']}/generate",
            headers=admin.headers,
        )
        client.post(
            f"/api/events/{event['id']}/certificates/{alice['id']}/send", headers=admin.headers
        )
        response = correct(
            client, admin.headers, alice["attendee_id"], email="alice.n@example.com"
        )
        assert response.status_code == 409, response.text

    def test_undelivered_certificate_is_corrected_rather_than_blocking(
        self, client, admin, db_session, event, rows
    ):
        # Generated but never sent: its number has never left the system, and
        # this is the exact moment a bad address is usually discovered.
        alice = rows["Alice Nguyen"]
        approve(client, admin.headers, event["id"], alice["id"])
        generated = client.post(
            f"/api/events/{event['id']}/certificates/{alice['id']}/generate",
            headers=admin.headers,
        )
        assert generated.status_code == 200, generated.text
        number = generated.json()["certificate_number"]

        response = correct(
            client, admin.headers, alice["attendee_id"], full_name="Alyce Nguyen"
        )
        assert response.status_code == 200, response.text
        assert response.json()["certificates_updated"] == [number]

        # The stored snapshot is what a re-issue renders from, so it has to
        # carry the corrected name or the PDF would keep printing the old one
        # while the public verification portal showed the new one.
        certificate = db_session.get(Certificate, generated.json()["id"])
        db_session.refresh(certificate)
        assert certificate.event_snapshot["fields"]["attendee_name"] == "Alyce Nguyen"
        # Everything else in the snapshot is untouched.
        assert certificate.event_snapshot["event_title"] == "Correction Flow CEU"

    def test_email_only_correction_leaves_certificates_alone(
        self, client, admin, event, rows
    ):
        alice = rows["Alice Nguyen"]
        approve(client, admin.headers, event["id"], alice["id"])
        client.post(
            f"/api/events/{event['id']}/certificates/{alice['id']}/generate",
            headers=admin.headers,
        )
        response = correct(
            client, admin.headers, alice["attendee_id"], email="alice.n@example.com"
        )
        assert response.status_code == 200, response.text
        # The email is not printed on the document, so nothing is re-rendered.
        assert response.json()["certificates_updated"] == []


class TestAuditAndAccess:
    def test_correction_records_before_and_after(self, client, admin, rows):
        cara = rows["Cara Fields"]
        correct(
            client,
            admin.headers,
            cara["attendee_id"],
            email="cara.fields@example.com",
            reason="Read off the sign-in sheet as .con",
        )
        entries = [
            entry
            for entry in audit_actions(client, admin.headers)
            if entry["action"] == "attendee.corrected"
        ]
        assert len(entries) == 1
        details = entries[0]["details"]
        assert details["before"] == {"full_name": "Cara Fields", "email": "cara-at-example.com"}
        assert details["after"]["email"] == "cara.fields@example.com"
        assert details["reason"] == "Read off the sign-in sheet as .con"
        assert entries[0]["actor_id"] == admin.id
        assert entries[0]["entity_type"] == "attendee"

    def test_presenters_cannot_correct_attendees(self, client, presenter, rows):
        response = correct(
            client, presenter.headers, rows["Cara Fields"]["attendee_id"], email="x@example.com"
        )
        assert response.status_code == 403, response.text

    def test_anonymous_callers_are_rejected(self, client, rows):
        response = client.patch(
            f"/api/attendees/{rows['Cara Fields']['attendee_id']}",
            json={"email": "x@example.com"},
        )
        assert response.status_code == 403, response.text

    def test_unknown_attendee_is_404(self, client, admin):
        response = correct(client, admin.headers, 999999, email="x@example.com")
        assert response.status_code == 404, response.text


class TestMultipleEvents:
    def test_correction_spans_every_event_a_shared_identity_is_on(
        self, client, admin, event, rows
    ):
        # Bob has a usable email, so he is one global Attendee linked to both
        # events. One correction therefore has to re-derive both rosters, not
        # just the one the admin happened to be looking at.
        second = create_event(client, admin.headers, title="Second CEU")
        upload_standard_roster(client, admin.headers, second["id"])
        bob_id = rows["Bob Ramos"]["attendee_id"]

        response = correct(client, admin.headers, bob_id, email="bob.ramos@newco.example.com")
        assert response.status_code == 200, response.text
        assert response.json()["events_recalculated"] == sorted([event["id"], second["id"]])

        for event_id in (event["id"], second["id"]):
            after = compliance_rows_by_name(client, admin.headers, event_id)["Bob Ramos"]
            assert after["email"] == "bob.ramos@newco.example.com", event_id

    def test_correcting_one_emailless_duplicate_does_not_touch_the_other(
        self, client, admin, event, rows
    ):
        """Two records for the same person, and why the merge guard matters.

        A name is not a global identity here (see services/attendee_match), so
        Cara -- whose sign-in-sheet address never normalized to anything usable
        -- is a *separate* attendee row on each event. Correcting one is
        scoped to that one, and pointing the second at the address the first
        now owns is exactly the collision the endpoint refuses.
        """
        second = create_event(client, admin.headers, title="Second CEU")
        upload_standard_roster(client, admin.headers, second["id"])
        first_cara = rows["Cara Fields"]["attendee_id"]
        second_cara = compliance_rows_by_name(client, admin.headers, second["id"])[
            "Cara Fields"
        ]["attendee_id"]
        assert first_cara != second_cara

        fixed = correct(client, admin.headers, first_cara, email="cara.fields@example.com")
        assert fixed.status_code == 200, fixed.text
        assert fixed.json()["events_recalculated"] == [event["id"]]
        assert fixed.json()["newly_eligible"] == [rows["Cara Fields"]["id"]]
        # The other event's Cara is untouched and still ineligible.
        assert (
            compliance_rows_by_name(client, admin.headers, second["id"])["Cara Fields"][
                "eligible"
            ]
            is False
        )

        # Giving the second record the same address is a merge, and is refused.
        clash = correct(client, admin.headers, second_cara, email="cara.fields@example.com")
        assert clash.status_code == 409, clash.text
        assert "merge" in clash.json()["detail"].lower()
