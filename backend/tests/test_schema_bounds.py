"""Every field bounded by a database column is bounded in Pydantic too.

Each case below used to be an unhandled 500: Pydantic accepted the value, the
request reached Postgres, and the column constraint raised at flush time with
nothing to tell the caller which field was wrong.

Note what these tests can and cannot prove. The suite runs on SQLite, which
ignores VARCHAR widths entirely, so an unbounded field here would *pass*
silently rather than 500 -- the 500 only ever happened against real Postgres.
What is pinned is therefore the bound itself: a 422 naming the field, on the
same limit the model declares.
"""
import pytest
from helpers_api import DEFAULT_EVENT, create_event, upload_csv
from sqlalchemy import select

from app.models.attendee import Attendee
from app.schemas.common import (
    EVENT_CEU_HOURS_MAX,
    EVENT_MODE_MAX,
    EVENT_NAME_MAX,
    EVENT_TITLE_MAX,
    EVENT_TYPE_MAX,
    EVENT_URL_MAX,
)
from app.services.identity import MAX_EMAIL_LENGTH, NAME_PART_MAX_LENGTH, normalize_email

# (field, the width of the column it is stored in). Kept beside the model
# limits so a widened column that forgets its schema bound shows up here.
BOUNDED_TEXT_FIELDS = [
    ("title", EVENT_TITLE_MAX),
    ("location", EVENT_NAME_MAX),
    ("presenter_name", EVENT_NAME_MAX),
    ("course_instructor", EVENT_NAME_MAX),
    ("certificate_title", EVENT_NAME_MAX),
    ("event_type", EVENT_TYPE_MAX),
    ("test_mode", EVENT_MODE_MAX),
    ("survey_mode", EVENT_MODE_MAX),
    ("post_test_url", EVENT_URL_MAX),
    ("external_survey_url", EVENT_URL_MAX),
]


def post_event(client, headers, **overrides):
    return client.post("/api/events", json={**DEFAULT_EVENT, **overrides}, headers=headers)


class TestEventTextBounds:
    @pytest.mark.parametrize("field,limit", BOUNDED_TEXT_FIELDS)
    def test_over_long_value_is_422_on_create(self, client, admin, field, limit):
        response = post_event(client, admin.headers, **{field: "x" * (limit + 1)})
        assert response.status_code == 422, response.text
        # The error has to say which field, or it is no better than the 500.
        assert field in response.text

    @pytest.mark.parametrize("field,limit", BOUNDED_TEXT_FIELDS)
    def test_value_at_the_limit_is_accepted(self, client, admin, field, limit):
        # Off-by-one in the safe direction is still a bug: a value the column
        # can hold must not be refused.
        response = post_event(client, admin.headers, **{field: "x" * limit})
        assert response.status_code == 201, response.text

    @pytest.mark.parametrize("field,limit", BOUNDED_TEXT_FIELDS)
    def test_over_long_value_is_422_on_update(self, client, admin, field, limit):
        event = create_event(client, admin.headers)
        response = client.put(
            f"/api/events/{event['id']}",
            json={field: "x" * (limit + 1)},
            headers=admin.headers,
        )
        assert response.status_code == 422, response.text

    def test_description_stays_unbounded(self, client, admin):
        # description is TEXT, which has no width; bounding it here would be a
        # limit the database never asked for.
        response = post_event(client, admin.headers, description="d" * 50_000)
        assert response.status_code == 201, response.text


class TestCeuHoursBounds:
    def test_above_the_numeric_precision_is_422(self, client, admin):
        # ceu_hours is Numeric(6, 2): 9999.99 is the largest value that fits,
        # and anything above it was a numeric field overflow at flush time.
        response = post_event(client, admin.headers, ceu_hours=10000)
        assert response.status_code == 422, response.text
        assert "ceu_hours" in response.text

    def test_at_the_precision_limit_is_accepted(self, client, admin):
        response = post_event(client, admin.headers, ceu_hours=float(EVENT_CEU_HOURS_MAX))
        assert response.status_code == 201, response.text

    @pytest.mark.parametrize("value", ["1e400", "NaN", "Infinity"])
    def test_non_finite_values_are_422(self, client, admin, value):
        response = post_event(client, admin.headers, ceu_hours=value)
        assert response.status_code == 422, response.text

    def test_zero_and_negative_stay_refused(self, client, admin):
        assert post_event(client, admin.headers, ceu_hours=0).status_code == 422
        assert post_event(client, admin.headers, ceu_hours=-1).status_code == 422

    def test_extra_decimal_places_are_still_accepted(self, client, admin):
        # Postgres rounds to the column's scale rather than failing, so this is
        # not an overflow and must not be turned into one.
        response = post_event(client, admin.headers, ceu_hours=1.005)
        assert response.status_code == 201, response.text

    def test_over_long_value_is_422_on_update(self, client, admin):
        event = create_event(client, admin.headers)
        response = client.put(
            f"/api/events/{event['id']}", json={"ceu_hours": 12345.67}, headers=admin.headers
        )
        assert response.status_code == 422, response.text


class TestAttendeeColumnWidths:
    """Values derived from a bounded field can still overflow a narrower column."""

    def test_over_long_email_never_becomes_an_identity(self):
        # Attendee.email / normalized_email are String(255) and a spreadsheet
        # cell has no width at all. An address longer than RFC 5321 allows is
        # not deliverable, so it is treated like any other unusable value.
        too_long = "a" * (MAX_EMAIL_LENGTH + 1) + "@example.com"
        assert normalize_email(too_long) is None
        assert normalize_email("a" * 60 + "@example.com") is not None

    def test_long_single_token_name_is_clipped_to_the_narrower_columns(
        self, client, admin, db_session
    ):
        # full_name is String(255) but first_name/last_name are String(120), so
        # a 200-character single token fits the field the API validates and
        # overflows the ones derived from it.
        event = create_event(client, admin.headers)
        token = client.get(f"/api/events/{event['id']}", headers=admin.headers).json()[
            "checkin_token"
        ]
        long_name = "N" * 200
        response = client.post(
            f"/api/public/checkin/{token}",
            json={"full_name": long_name, "email": "long.name@example.com"},
        )
        assert response.status_code == 200, response.text

        attendee = db_session.scalar(
            select(Attendee).where(Attendee.email == "long.name@example.com")
        )
        assert len(attendee.first_name) <= NAME_PART_MAX_LENGTH
        # The authoritative value keeps the whole name.
        assert attendee.full_name == long_name

    def test_oversized_spreadsheet_cells_do_not_break_an_import(
        self, client, admin, db_session
    ):
        event = create_event(client, admin.headers)
        csv_text = (
            "Full Name,Email,Company,License Number\n"
            f"Pat Vega,pat.vega@example.com,{'C' * 4000},{'L' * 4000}\n"
        )
        response = upload_csv(client, admin.headers, event["id"], "registration", csv_text)
        assert response.status_code == 201, response.text

        attendee = db_session.scalar(
            select(Attendee).where(Attendee.email == "pat.vega@example.com")
        )
        assert len(attendee.company) <= 255
        assert len(attendee.license_number) <= 120
