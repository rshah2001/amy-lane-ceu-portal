"""Data-integrity regressions for the file import path.

Every test here pins a bug that put the wrong data in front of the people who
sign CEU certificates: a failing score stored as a passing one, an empty
re-upload erasing an event's results, two attendees silently becoming one. They
are written against the HTTP surface wherever possible, because that is where
the damage was observed.
"""
import threading
import time
from decimal import Decimal
from io import BytesIO

import pytest
import sqlalchemy
from openpyxl import Workbook
from sqlalchemy import select

import app.api.uploads as uploads_module
from app.models.attendee import Attendee
from app.models.event_attendee import EventAttendee
from app.services.csv_import import (
    EmptyImportError,
    describe_score_basis,
    looks_like_csv_text,
    resolve_score_basis,
)
from app.services.identity import core_name, names_are_variants
from helpers_api import (
    compliance_rows_by_name,
    create_event,
    upload_csv,
    upload_document,
)

XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@pytest.fixture()
def event(client, admin, presenter):
    return create_event(client, admin.headers, assigned_presenter_id=presenter.id)


def notices(body: dict) -> list[str]:
    return [error["message"] for error in body["parse_errors"] if error.get("level") == "info"]


def problems(body: dict) -> list[str]:
    return [error["message"] for error in body["parse_errors"] if error.get("level") != "info"]


def upload_scores(client, headers, event_id, csv_text, score_basis=None):
    """Post a post-test CSV, optionally stating what a bare score means.

    Kept local rather than in helpers_api: score_basis is a form field like
    sheet_format, and the shared helper only knows about the latter.
    """
    return client.post(
        f"/api/events/{event_id}/uploads/post_test",
        headers=headers,
        files={"file": ("scores.csv", csv_text.encode(), "text/csv")},
        data={"score_basis": score_basis} if score_basis else None,
    )


# --- P0-1: the score unit is decided once per column, never per cell --------

AMBIGUOUS_SCORES = (
    "Full Name,Email,Score\n"
    "Fay Ling,fay.ling@example.com,8\n"
    "Ada Pass,ada.pass@example.com,9\n"
)


class TestScoreBasisIsPerColumn:
    def test_ambiguous_column_is_refused_not_guessed(self, client, admin, event):
        # The live bug: a raw 8 meaning 8% was multiplied to 80.0 -- exactly the
        # pass mark -- and the attendee was issued a certificate for a failed
        # test. A column that cannot be read with certainty is now refused.
        response = upload_scores(client, admin.headers, event["id"], AMBIGUOUS_SCORES)
        assert response.status_code == 400, response.text
        detail = response.json()["detail"]
        assert "ambiguous" in detail
        # The message has to tell the uploader how to fix it.
        assert "%" in detail and "x/10" in detail
        assert not compliance_rows_by_name(client, admin.headers, event["id"])

    def test_percent_column_reads_a_bare_eight_as_eight_percent(self, client, admin, event):
        # One value above 10 settles the column: it is percentages, so an 8 in
        # it is 8% -- a fail -- and must not become 80.
        response = upload_scores(
            client,
            admin.headers,
            event["id"],
            "Full Name,Email,Score\n"
            "Fay Ling,fay.ling@example.com,8\n"
            "Ada Pass,ada.pass@example.com,88\n",
        )
        assert response.status_code == 201, response.text
        rows = compliance_rows_by_name(client, admin.headers, event["id"])
        assert rows["Fay Ling"]["test_score"] == 8.0
        assert rows["Fay Ling"]["eligible"] is False
        assert "Post-test score below 80%" in rows["Fay Ling"]["eligibility_reasons"]
        assert rows["Ada Pass"]["test_score"] == 88.0

    def test_percent_sign_anywhere_settles_the_whole_column(self, client, admin, event):
        response = upload_scores(
            client,
            admin.headers,
            event["id"],
            "Full Name,Email,Score\n"
            "Percy Cent,percy.cent@example.com,85%\n"
            "Fay Ling,fay.ling@example.com,8\n",
        )
        assert response.status_code == 201, response.text
        rows = compliance_rows_by_name(client, admin.headers, event["id"])
        assert rows["Fay Ling"]["test_score"] == 8.0

    def test_fraction_cells_are_read_on_their_own_terms(self, client, admin, event):
        # "8/10" states its own denominator, so it is unambiguous even in a
        # column that is otherwise percentages.
        response = upload_scores(
            client,
            admin.headers,
            event["id"],
            "Full Name,Email,Score\n"
            "Fran Action,fran.action@example.com,8/10\n"
            "Ada Pass,ada.pass@example.com,88\n",
        )
        assert response.status_code == 201, response.text
        rows = compliance_rows_by_name(client, admin.headers, event["id"])
        assert rows["Fran Action"]["test_score"] == 80.0

    def test_explicit_out_of_ten_basis_overrides_inference(self, client, admin, event):
        response = upload_scores(
            client, admin.headers, event["id"], AMBIGUOUS_SCORES, score_basis="out_of_10"
        )
        assert response.status_code == 201, response.text
        rows = compliance_rows_by_name(client, admin.headers, event["id"])
        assert rows["Fay Ling"]["test_score"] == 80.0
        assert rows["Ada Pass"]["test_score"] == 90.0

    def test_explicit_percent_basis_keeps_a_failing_eight_failing(self, client, admin, event):
        response = upload_scores(
            client, admin.headers, event["id"], AMBIGUOUS_SCORES, score_basis="percent"
        )
        assert response.status_code == 201, response.text
        rows = compliance_rows_by_name(client, admin.headers, event["id"])
        assert rows["Fay Ling"]["test_score"] == 8.0
        assert rows["Ada Pass"]["test_score"] == 9.0

    def test_explicit_fraction_basis_reads_excel_decimals(self, client, admin, event):
        response = upload_scores(
            client,
            admin.headers,
            event["id"],
            "Full Name,Email,Score\nDecy Mal,decy.mal@example.com,0.85\n",
            score_basis="out_of_1",
        )
        assert response.status_code == 201, response.text
        rows = compliance_rows_by_name(client, admin.headers, event["id"])
        assert rows["Decy Mal"]["test_score"] == 85.0

    def test_invalid_score_basis_returns_400(self, client, admin, event):
        response = upload_scores(
            client, admin.headers, event["id"], AMBIGUOUS_SCORES, score_basis="vibes"
        )
        assert response.status_code == 400, response.text

    def test_response_always_reports_how_scores_were_read(self, client, admin, event):
        inferred = upload_scores(
            client,
            admin.headers,
            event["id"],
            "Full Name,Email,Score\nAda Pass,ada.pass@example.com,88\n",
        )
        assert inferred.status_code == 201, inferred.text
        assert any("percentages" in note for note in notices(inferred.json()))
        # A file that reads cleanly is still "processed", not "with errors":
        # the interpretation notice is information, not a problem.
        assert inferred.json()["parse_status"] == "processed"

        chosen = upload_scores(
            client, admin.headers, event["id"], AMBIGUOUS_SCORES, score_basis="out_of_10"
        )
        assert chosen.status_code == 201, chosen.text
        assert any(
            "out of 10" in note and "as selected on this upload" in note
            for note in notices(chosen.json())
        )

    def test_xlsx_percent_cells_are_reported_as_written(self, client, admin, event):
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.append(["Name", "Email", "Score"])
        worksheet.append(["Exel Percent", "exel.percent@example.com", 0.9])
        worksheet["C2"].number_format = "0%"
        output = BytesIO()
        workbook.save(output)
        response = upload_document(
            client,
            admin.headers,
            event["id"],
            "post_test",
            "results.xlsx",
            output.getvalue(),
            XLSX_MEDIA_TYPE,
        )
        assert response.status_code == 201, response.text
        # Excel's percent-formatted 0.9 reaches the parser as "90%", so every
        # cell states its own unit and nothing had to be inferred.
        assert any("exactly as written" in note for note in notices(response.json()))
        rows = compliance_rows_by_name(client, admin.headers, event["id"])
        assert rows["Exel Percent"]["test_score"] == 90.0

    def test_resolve_score_basis_rules(self):
        assert resolve_score_basis(None, ["85%", "8"]) == "percent"
        assert resolve_score_basis(None, ["72", "8"]) == "percent"
        # Every cell states its own unit: nothing left to infer.
        assert resolve_score_basis(None, ["8/10", "9/10"]) is None
        assert resolve_score_basis("out_of_10", ["8", "9"]) == "out_of_10"
        with pytest.raises(ValueError, match="ambiguous"):
            resolve_score_basis(None, ["8", "9", "10"])
        with pytest.raises(ValueError, match="ambiguous"):
            resolve_score_basis(None, ["0.85", "0.92"])
        assert "exactly as written" in describe_score_basis(None, False)


# --- P0-2: an import that lands nothing must not erase what is there -------

SCORED_ROSTER = (
    "Full Name,Email,Score\n"
    "Ada Pass,ada.pass@example.com,80\n"
    "Ben Best,ben.best@example.com,88\n"
)
NO_NAME_COLUMNS_CSV = "Company,Notes\nMobility Works,Sent by fax\n"


class TestEmptyImportIsNotDestructive:
    def _seed_scores(self, client, admin, event):
        response = upload_scores(client, admin.headers, event["id"], SCORED_ROSTER)
        assert response.status_code == 201, response.text
        rows = compliance_rows_by_name(client, admin.headers, event["id"])
        assert rows["Ada Pass"]["test_score"] == 80.0
        assert rows["Ben Best"]["test_score"] == 88.0
        return rows

    def test_reupload_with_no_names_keeps_every_score(self, client, admin, event):
        # The live repro: posting a Company,Notes sheet to the post-test slot
        # returned 201 and reset two attendees from 80/88 to no score at all.
        self._seed_scores(client, admin, event)
        response = upload_scores(client, admin.headers, event["id"], NO_NAME_COLUMNS_CSV)
        assert response.status_code == 400, response.text
        assert "No attendee names could be read" in response.json()["detail"]

        rows = compliance_rows_by_name(client, admin.headers, event["id"])
        assert rows["Ada Pass"]["test_score"] == 80.0, "an empty import wiped a real score"
        assert rows["Ada Pass"]["test_completed"] is True
        assert rows["Ben Best"]["test_score"] == 88.0

    def test_reupload_whose_rows_all_fail_keeps_every_score(self, client, admin, event):
        # Names read fine, but not one score could be used: still nothing to
        # put back, so still nothing may be taken away.
        self._seed_scores(client, admin, event)
        response = upload_scores(
            client,
            admin.headers,
            event["id"],
            "Full Name,Email,Score\nAda Pass,ada.pass@example.com,eight\n",
        )
        assert response.status_code == 400, response.text
        assert "left unchanged" in response.json()["detail"]
        rows = compliance_rows_by_name(client, admin.headers, event["id"])
        assert rows["Ada Pass"]["test_score"] == 80.0

    def test_ambiguous_rescore_keeps_every_score(self, client, admin, event):
        self._seed_scores(client, admin, event)
        response = upload_scores(client, admin.headers, event["id"], AMBIGUOUS_SCORES)
        assert response.status_code == 400, response.text
        rows = compliance_rows_by_name(client, admin.headers, event["id"])
        assert rows["Ada Pass"]["test_score"] == 80.0

    def test_empty_attendance_reupload_keeps_attendance(self, client, admin, event):
        response = upload_csv(
            client,
            admin.headers,
            event["id"],
            "attendance",
            "Full Name,Email\nAda Pass,ada.pass@example.com\n",
        )
        assert response.status_code == 201, response.text
        response = upload_csv(
            client, admin.headers, event["id"], "attendance", NO_NAME_COLUMNS_CSV
        )
        assert response.status_code == 400, response.text
        rows = compliance_rows_by_name(client, admin.headers, event["id"])
        assert rows["Ada Pass"]["attended"] is True

    def test_empty_survey_reupload_keeps_survey_flags(self, client, admin, event):
        response = upload_csv(
            client,
            admin.headers,
            event["id"],
            "survey",
            "Full Name,Email,Completed\nAda Pass,ada.pass@example.com,Yes\n",
        )
        assert response.status_code == 201, response.text
        response = upload_csv(client, admin.headers, event["id"], "survey", NO_NAME_COLUMNS_CSV)
        assert response.status_code == 400, response.text
        rows = compliance_rows_by_name(client, admin.headers, event["id"])
        assert rows["Ada Pass"]["survey_completed"] is True

    def test_a_real_reupload_still_replaces_file_results(self, client, admin, event):
        # The reset is only skipped when there is nothing to put back; a real
        # re-upload must still replace what the last one wrote.
        self._seed_scores(client, admin, event)
        response = upload_scores(
            client,
            admin.headers,
            event["id"],
            "Full Name,Email,Score\nAda Pass,ada.pass@example.com,95\n",
        )
        assert response.status_code == 201, response.text
        rows = compliance_rows_by_name(client, admin.headers, event["id"])
        assert rows["Ada Pass"]["test_score"] == 95.0
        assert rows["Ben Best"]["test_score"] is None, "the replaced file's rows must be cleared"

    def test_web_test_results_survive_the_new_import_path(self, client, admin):
        # The web-vs-upload sourcing rule predates this fix and must hold
        # through it: a public test submission is not file-sourced.
        event = create_event(
            client,
            admin.headers,
            test_mode="internal",
            test_questions=[
                {"id": "q1", "prompt": "2 + 2?", "choices": ["3", "4"], "correct_index": 1}
            ],
        )
        submitted = client.post(
            f"/api/public/tests/{event['test_token']}",
            json={"full_name": "Sam Lee", "email": "sam.lee@example.com", "answers": {"q1": 1}},
        )
        assert submitted.status_code == 200, submitted.text
        response = upload_scores(client, admin.headers, event["id"], SCORED_ROSTER)
        assert response.status_code == 201, response.text
        # ...and a later failed import must not wipe it either.
        assert (
            upload_scores(client, admin.headers, event["id"], NO_NAME_COLUMNS_CSV).status_code
            == 400
        )
        rows = compliance_rows_by_name(client, admin.headers, event["id"])
        assert rows["Sam Lee"]["test_score"] == 100.0
        assert rows["Ada Pass"]["test_score"] == 80.0

    def test_empty_import_records_no_upload_row(self, client, admin, event):
        response = upload_csv(
            client, admin.headers, event["id"], "attendance", NO_NAME_COLUMNS_CSV
        )
        assert response.status_code == 400, response.text
        listed = client.get(f"/api/events/{event['id']}/uploads", headers=admin.headers)
        assert listed.json() == [], "a refused import must not look like a stored upload"

    def test_process_rows_raises_before_touching_the_database(self, db_session, admin, client):
        from app.services.csv_import import process_rows

        event = create_event(client, admin.headers)
        with pytest.raises(EmptyImportError) as caught:
            process_rows(db_session, event["id"], "post_test", [{"Company": "Acme"}])
        assert caught.value.row_count == 1
        assert any("No attendee names" in error["message"] for error in caught.value.errors)


# --- P0-3: two people with one name must not become one person -------------

TWO_JOHN_SMITHS = "Full Name,Email\nJohn Smith,\nJohn Smith,\n"


class TestIndistinguishableRowsAreRefused:
    def test_two_email_less_rows_with_one_name_are_flagged(self, client, admin, event):
        # Both rows used to collapse into a single attendee: row_count 2, a
        # roster of 1, no errors -- and one real person's certificate silently
        # never existed.
        response = upload_csv(client, admin.headers, event["id"], "attendance", TWO_JOHN_SMITHS)
        assert response.status_code == 400, response.text
        detail = response.json()["detail"]
        assert "left unchanged" in detail

        response = upload_csv(
            client,
            admin.headers,
            event["id"],
            "attendance",
            "Full Name,Email\n"
            "Jane Doe,jane.doe@example.com\n"
            "John Smith,\n"
            "John Smith,\n",
        )
        assert response.status_code == 201, response.text
        messages = problems(response.json())
        assert len(messages) == 2, messages
        assert all('rows named "John Smith" have no email address' in m for m in messages)
        assert all("add emails to tell them apart" in m.lower() for m in messages)
        rows = compliance_rows_by_name(client, admin.headers, event["id"])
        assert "John Smith" not in rows, "an unresolvable duplicate must not be imported"
        assert "Jane Doe" in rows

    def test_duplicate_names_with_emails_are_two_people(self, client, admin, event):
        response = upload_csv(
            client,
            admin.headers,
            event["id"],
            "attendance",
            "Full Name,Email\n"
            "John Smith,john.smith@dealer-a.com\n"
            "John Smith,john.smith@dealer-b.com\n",
        )
        assert response.status_code == 201, response.text
        assert problems(response.json()) == []
        rows = client.get(
            f"/api/events/{event['id']}/compliance", headers=admin.headers
        ).json()
        assert sorted(row["email"] for row in rows) == [
            "john.smith@dealer-a.com",
            "john.smith@dealer-b.com",
        ]

    def test_the_same_person_listed_twice_with_one_email_still_dedupes(
        self, client, admin, event
    ):
        response = upload_csv(
            client,
            admin.headers,
            event["id"],
            "attendance",
            "Full Name,Email\n"
            "John Smith,john.smith@dealer-a.com\n"
            "John Smith,john.smith@dealer-a.com\n",
        )
        assert response.status_code == 201, response.text
        assert problems(response.json()) == []
        assert len(compliance_rows_by_name(client, admin.headers, event["id"])) == 1

    def test_email_less_name_variants_in_one_file_are_flagged(self, client, admin, event):
        # "John Smith" and "John A. Smith" on one sheet with no emails could be
        # one person written twice or two people; either way, not a guess.
        response = upload_csv(
            client,
            admin.headers,
            event["id"],
            "attendance",
            "Full Name,Email\nJane Doe,jane.doe@example.com\nJohn Smith,\nJohn A. Smith,\n",
        )
        assert response.status_code == 201, response.text
        messages = problems(response.json())
        assert len(messages) == 2, messages
        assert all("may be the same person" in message for message in messages)

    def test_different_middle_initials_are_not_a_collision(self, client, admin, event):
        response = upload_csv(
            client,
            admin.headers,
            event["id"],
            "attendance",
            "Full Name,Email\nJohn A. Smith,\nJohn C. Smith,\n",
        )
        assert response.status_code == 201, response.text
        assert problems(response.json()) == []
        assert len(compliance_rows_by_name(client, admin.headers, event["id"])) == 2

    def test_cross_event_scoping_is_not_regressed(self, client, admin, db_session):
        # Guards commit 2b94d12: one email-less name on two events is two
        # people, and the duplicate check must not merge them into one.
        events = [
            create_event(client, admin.headers, title="First"),
            create_event(client, admin.headers, title="Second"),
        ]
        for created in events:
            response = upload_csv(
                client, admin.headers, created["id"], "attendance", "Name\nJohn Smith\n"
            )
            assert response.status_code == 201, response.text
        attendees = list(
            db_session.scalars(select(Attendee).where(Attendee.normalized_name == "john smith"))
        )
        assert len(attendees) == 2
        for attendee in attendees:
            linked = list(
                db_session.scalars(
                    select(EventAttendee.event_id).where(
                        EventAttendee.attendee_id == attendee.id
                    )
                )
            )
            assert len(linked) == 1


# --- P1: name normalization is applied on every path -----------------------


class TestNameNormalizationIsShared:
    def test_qr_checkin_matches_the_sheets_natural_order_name(self, client, admin):
        # A Teams-style "Smith, Bob" typed into the public check-in used to
        # create a second attendee beside the sheet's "Bob Smith".
        event = create_event(client, admin.headers)
        response = upload_csv(client, admin.headers, event["id"], "registration", "Name\nBob Smith\n")
        assert response.status_code == 201, response.text
        detail = client.get(f"/api/events/{event['id']}", headers=admin.headers).json()
        response = client.post(
            f"/api/public/checkin/{detail['checkin_token']}",
            json={"full_name": "Smith, Bob", "email": "bob.smith@example.com"},
        )
        assert response.status_code == 200, response.text

        rows = compliance_rows_by_name(client, admin.headers, event["id"])
        assert list(rows) == ["Bob Smith"], "the check-in created a second Bob Smith"
        assert rows["Bob Smith"]["attended"] is True
        assert rows["Bob Smith"]["email"] == "bob.smith@example.com"


class TestEmailIsStoredNormalized:
    def test_display_name_email_is_eligible_and_sendable(self, client, admin, event):
        # "Bob Smith <bob@x.com>" matched fine but was stored raw, so the
        # eligibility check called it invalid and no certificate was issued.
        response = upload_csv(
            client,
            admin.headers,
            event["id"],
            "attendance",
            "Full Name,Email\nBob Smith,Bob Smith <bob@example.com>\n",
        )
        assert response.status_code == 201, response.text
        rows = compliance_rows_by_name(client, admin.headers, event["id"])
        assert rows["Bob Smith"]["email"] == "bob@example.com"
        assert rows["Bob Smith"]["has_valid_email"] is True
        assert "Missing or invalid email" not in rows["Bob Smith"]["eligibility_reasons"]

    def test_mailto_email_is_stored_without_the_scheme(self, client, admin, event):
        # The mirror image: "mailto:c@x.com" passed the eligibility regex but
        # was not a sendable address.
        response = upload_csv(
            client,
            admin.headers,
            event["id"],
            "attendance",
            "Full Name,Email\nCass Ing,mailto:cass@example.com\n",
        )
        assert response.status_code == 201, response.text
        rows = compliance_rows_by_name(client, admin.headers, event["id"])
        assert rows["Cass Ing"]["email"] == "cass@example.com"
        assert rows["Cass Ing"]["has_valid_email"] is True

    def test_unusable_email_text_is_kept_and_stays_ineligible(self, client, admin, event):
        # Junk is left visible so an admin can see what to fix -- and it must
        # still fail the eligibility check.
        response = upload_csv(
            client,
            admin.headers,
            event["id"],
            "attendance",
            "Full Name,Email\nNora Brooks,nora_at_example.com\n",
        )
        assert response.status_code == 201, response.text
        rows = compliance_rows_by_name(client, admin.headers, event["id"])
        assert rows["Nora Brooks"]["email"] == "nora_at_example.com"
        assert rows["Nora Brooks"]["has_valid_email"] is False


class TestCompletedFlagParsing:
    def _survey_flags(self, client, admin, event_id, csv_text):
        response = upload_csv(client, admin.headers, event_id, "survey", csv_text)
        assert response.status_code == 201, response.text
        rows = compliance_rows_by_name(client, admin.headers, event_id)
        return {name: row["survey_completed"] for name, row in rows.items()}

    def test_blank_cell_is_not_completed(self, client, admin, event):
        flags = self._survey_flags(
            client,
            admin,
            event["id"],
            "Full Name,Email,Completed\n"
            "Ada Pass,ada.pass@example.com,Yes\n"
            "Blank Bill,blank.bill@example.com,\n",
        )
        assert flags["Ada Pass"] is True
        assert flags["Blank Bill"] is False, "a blank cell was read as completed"

    def test_did_not_attend_is_not_completed(self, client, admin, event):
        flags = self._survey_flags(
            client,
            admin,
            event["id"],
            "Full Name,Email,Completed\n"
            "Ada Pass,ada.pass@example.com,Yes\n"
            "Abby Sent,abby.sent@example.com,Did not attend\n"
            "Norma Ply,norma.ply@example.com,N/A\n"
            "Sam Absent,sam.absent@example.com,Absent\n",
        )
        assert flags["Ada Pass"] is True
        assert flags["Abby Sent"] is False
        assert flags["Norma Ply"] is False
        assert flags["Sam Absent"] is False

    def test_file_without_a_completed_column_still_means_completed(self, client, admin, event):
        # A survey export with no status column IS the list of respondents.
        flags = self._survey_flags(
            client,
            admin,
            event["id"],
            "Full Name,Email\nAda Pass,ada.pass@example.com\n",
        )
        assert flags["Ada Pass"] is True


class TestUploadGateMatchesTheDecoder:
    def test_cp1252_csv_is_accepted(self, client, admin, event):
        contents = "Full Name,Email\nRenée Dupont,renee@example.com\n".encode("cp1252")
        response = upload_document(
            client, admin.headers, event["id"], "attendance", "roster.csv", contents, "text/csv"
        )
        assert response.status_code == 201, response.text
        assert "Renee Dupont" in compliance_rows_by_name(client, admin.headers, event["id"]) or (
            "Renée Dupont" in compliance_rows_by_name(client, admin.headers, event["id"])
        )

    def test_utf16_csv_is_accepted(self, client, admin, event):
        contents = "Full Name,Email\nUta Sixteen,uta@example.com\n".encode("utf-16")
        response = upload_document(
            client, admin.headers, event["id"], "attendance", "roster.csv", contents, "text/csv"
        )
        assert response.status_code == 201, response.text
        assert "Uta Sixteen" in compliance_rows_by_name(client, admin.headers, event["id"])

    def test_binary_named_csv_is_still_rejected(self, client, admin, event):
        png = b"\x89PNG\r\n\x1a\n" + bytes(range(32)) * 8
        response = upload_document(
            client, admin.headers, event["id"], "attendance", "roster.csv", png, "text/csv"
        )
        assert response.status_code == 400, response.text

    def test_gate_helper_agrees_with_the_decoder(self):
        assert looks_like_csv_text("Name\nAda\n".encode("utf-16"))
        assert looks_like_csv_text("Name\nRenée\n".encode("cp1252"))
        assert not looks_like_csv_text(b"PK\x03\x04" + bytes(range(32)))
        assert not looks_like_csv_text(b"")


# --- P1: middle initials and generational suffixes -------------------------


class TestNameVariantMatching:
    def test_middle_initial_matches_the_same_event_attendee(self, client, admin, event):
        assert (
            upload_csv(
                client, admin.headers, event["id"], "registration", "Name\nBob Smith\n"
            ).status_code
            == 201
        )
        response = upload_csv(
            client, admin.headers, event["id"], "attendance", "Name\nBob A. Smith\n"
        )
        assert response.status_code == 201, response.text
        rows = compliance_rows_by_name(client, admin.headers, event["id"])
        assert len(rows) == 1, "a middle initial split one person into two"
        assert rows["Bob Smith"]["attended"] is True
        # A merge on anything less than an email is always flagged for review.
        assert any("confirm they are the same person" in note for note in notices(response.json()))

    def test_generational_suffix_matches(self, client, admin, event):
        assert (
            upload_csv(
                client, admin.headers, event["id"], "registration", "Name\nBob Smith Jr.\n"
            ).status_code
            == 201
        )
        response = upload_csv(
            client, admin.headers, event["id"], "attendance", "Name\nBob Smith\n"
        )
        assert response.status_code == 201, response.text
        assert len(compliance_rows_by_name(client, admin.headers, event["id"])) == 1

    def test_junior_and_senior_stay_two_people(self, client, admin, event):
        response = upload_csv(
            client,
            admin.headers,
            event["id"],
            "attendance",
            "Full Name,Email\nBob Smith Jr.,\nBob Smith Sr.,\n",
        )
        assert response.status_code == 201, response.text
        assert problems(response.json()) == []
        rows = compliance_rows_by_name(client, admin.headers, event["id"])
        assert len(rows) == 2, "a father and son were merged into one certificate"

    def test_two_possible_variants_are_left_for_a_human(self, client, admin, event):
        # Two candidates on the event means the file cannot say which is meant,
        # so nothing is merged and the ambiguity is reported.
        assert (
            upload_csv(
                client,
                admin.headers,
                event["id"],
                "registration",
                "Full Name,Email\n"
                "Bob A. Smith,bob.a@example.com\n"
                "Bob C. Smith,bob.c@example.com\n",
            ).status_code
            == 201
        )
        response = upload_csv(
            client, admin.headers, event["id"], "attendance", "Name\nBob Smith\n"
        )
        assert response.status_code == 201, response.text
        assert any("could be any of" in note for note in notices(response.json()))
        assert len(compliance_rows_by_name(client, admin.headers, event["id"])) == 3

    def test_variant_rules_are_conservative(self):
        assert names_are_variants("Bob Smith", "Bob A. Smith")
        assert names_are_variants("Bob Smith", "Bob Smith Jr.")
        assert names_are_variants("Bob A. Smith", "Bob Andrew Smith")
        assert not names_are_variants("Bob Smith Jr.", "Bob Smith Sr.")
        assert not names_are_variants("Bob A. Smith", "Bob C. Smith")
        assert not names_are_variants("Bob Smith", "Rob Smith")
        assert not names_are_variants("Bob Smith", "Bob Smyth")
        # A middle name spelled out on one side only is still an omission.
        assert names_are_variants("Mary Ann Smith", "Mary Smith")
        assert not names_are_variants("Mary Ann Smith", "Mary Beth Smith")
        # One token is too little to merge on.
        assert not names_are_variants("Smith", "Bob Smith")
        assert core_name("Bob A. Smith Jr.") == "bob smith"


# --- Performance: one import must not mean one query per row ---------------


class TestImportDoesNotQueryPerRow:
    def test_import_statement_count_is_bounded(self, client, admin, engine):
        event = create_event(client, admin.headers)
        rows = 60
        csv_text = "Full Name,Email\n" + "".join(
            f"Person {index},person{index}@example.com\n" for index in range(rows)
        )
        statements: list[str] = []

        def record(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement.strip().split()[0].upper())

        sqlalchemy.event.listen(engine, "before_cursor_execute", record)
        try:
            response = upload_csv(client, admin.headers, event["id"], "attendance", csv_text)
        finally:
            sqlalchemy.event.remove(engine, "before_cursor_execute", record)
        assert response.status_code == 201, response.text

        selects = statements.count("SELECT")
        # Before the roster was batch-loaded this was ~3 SELECTs per row plus a
        # lazy load per attendee during the compliance recalculation.
        assert selects < 20, f"{selects} SELECTs for {rows} rows looks like an N+1"

    def test_second_import_of_the_same_roster_is_also_bounded(self, client, admin, engine):
        event = create_event(client, admin.headers)
        csv_text = "Full Name,Email\n" + "".join(
            f"Person {index},person{index}@example.com\n" for index in range(40)
        )
        assert (
            upload_csv(client, admin.headers, event["id"], "attendance", csv_text).status_code
            == 201
        )
        statements: list[str] = []

        def record(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement.strip().split()[0].upper())

        sqlalchemy.event.listen(engine, "before_cursor_execute", record)
        try:
            response = upload_csv(client, admin.headers, event["id"], "attendance", csv_text)
        finally:
            sqlalchemy.event.remove(engine, "before_cursor_execute", record)
        assert response.status_code == 201, response.text
        # Matching 40 existing attendees must not re-query the roster per row.
        assert statements.count("SELECT") < 20


# --- The upload endpoint must not freeze the API ---------------------------


class TestUploadDoesNotBlockTheEventLoop:
    def test_health_stays_responsive_during_a_slow_upload(
        self, client, admin, event, monkeypatch
    ):
        # Parsing, OCR and the database writes are all synchronous; run on the
        # event loop they froze every other request for the whole upload (15+
        # minutes for a legal-size scanned sign-in sheet).
        real_process = uploads_module.process_document
        started = threading.Event()

        def slow_process(*args, **kwargs):
            started.set()
            time.sleep(2)
            return real_process(*args, **kwargs)

        monkeypatch.setattr(uploads_module, "process_document", slow_process)
        outcome: dict[str, object] = {}

        def run_upload():
            outcome["response"] = upload_csv(
                client,
                admin.headers,
                event["id"],
                "attendance",
                "Full Name,Email\nAda Pass,ada.pass@example.com\n",
            )

        worker = threading.Thread(target=run_upload)
        worker.start()
        try:
            assert started.wait(10), "the upload never started"
            began = time.monotonic()
            health = client.get("/api/health")
            elapsed = time.monotonic() - began
            assert health.status_code == 200
            assert elapsed < 1.5, f"/api/health waited {elapsed:.1f}s on the upload"
        finally:
            worker.join(30)
        assert outcome["response"].status_code == 201, outcome["response"].text

    def test_oversized_upload_is_rejected_before_parsing(
        self, client, admin, event, monkeypatch
    ):
        def fail(*args, **kwargs):
            raise AssertionError("an oversized upload reached the parser")

        monkeypatch.setattr(uploads_module, "process_document", fail)
        monkeypatch.setattr(uploads_module, "MAX_UPLOAD_BYTES", 4096)
        row = "Padding Person,padding.person@example.com\n"
        response = upload_csv(
            client,
            admin.headers,
            event["id"],
            "attendance",
            "Full Name,Email\n" + row * 400,
        )
        assert response.status_code == 413, response.text
        assert "limit" in response.json()["detail"]


def test_passing_score_boundary_is_unchanged(client, admin):
    """The pass mark itself is untouched by the score-basis work."""
    event = create_event(client, admin.headers)
    response = upload_csv(
        client,
        admin.headers,
        event["id"],
        "post_test",
        "Full Name,Email,Score\n"
        "Just Passed,just.passed@example.com,80\n"
        "Just Failed,just.failed@example.com,79.99\n",
    )
    assert response.status_code == 201, response.text
    rows = compliance_rows_by_name(client, admin.headers, event["id"])
    assert rows["Just Passed"]["test_score"] == float(Decimal("80.00"))
    assert "Post-test score below 80%" not in rows["Just Passed"]["eligibility_reasons"]
    assert "Post-test score below 80%" in rows["Just Failed"]["eligibility_reasons"]
