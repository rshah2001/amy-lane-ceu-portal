import unittest
from io import BytesIO
from datetime import date

from openpyxl import Workbook
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.db.base import Base
from app.models.event_attendee import EventAttendee
from app.models.training_event import TrainingEvent
from app.models.user import User
from app.services.csv_import import (
    parse_image_bytes,
    parse_pdf_bytes,
    parse_xlsx_bytes,
    process_csv,
    process_document,
)


def _fixture_font() -> ImageFont.FreeTypeFont:
    """Large, portable font for OCR fixtures: Pillow's bundled scalable
    default (10.1+), so the tests don't depend on any OS-specific font path."""
    return ImageFont.load_default(size=30)


class ComplianceWorkflowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        user = User(
            email="presenter@example.com",
            full_name="Test Presenter",
            role="presenter",
            hashed_password="not-used",
        )
        self.db.add(user)
        self.db.flush()
        event = TrainingEvent(
            title="Test CEU",
            event_date=date(2026, 6, 8),
            ceu_hours=2,
            created_by_id=user.id,
        )
        self.db.add(event)
        self.db.commit()
        self.event_id = event.id

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def upload(self, file_type: str, content: str) -> None:
        process_csv(self.db, self.event_id, file_type, content.encode())
        self.db.commit()

    def test_matches_attendees_and_applies_all_rules(self) -> None:
        self.upload(
            "registration",
            "Full Name,Email,Company\n"
            "Maya Chen,maya.chen@example.com,Northline\n"
            "Owen Patel,owen.patel@example.com,Northline\n"
            "Nora Brooks,nora_at_example.com,Independent\n",
        )
        self.upload(
            "attendance",
            "Name,Email\n"
            "MAYA CHEN,maya.chen@example.com\n"
            "Owen Patel,owen.patel@example.com\n"
            "Nora Brooks,nora_at_example.com\n",
        )
        self.upload(
            "post_test",
            "Participant Name,Email,Score\n"
            "Maya Chen,maya.chen@example.com,94\n"
            "Owen Patel,owen.patel@example.com,79\n"
            "Nora Brooks,nora_at_example.com,91\n",
        )
        self.upload(
            "survey",
            "Full Name,Email,Completed\n"
            "Maya Chen,maya.chen@example.com,Yes\n"
            "Owen Patel,owen.patel@example.com,Yes\n"
            "Nora Brooks,nora_at_example.com,Yes\n",
        )

        links = list(
            self.db.scalars(
                select(EventAttendee).where(EventAttendee.event_id == self.event_id).order_by(EventAttendee.id)
            )
        )
        by_name = {link.attendee.full_name: link for link in links}

        self.assertEqual(len(links), 3)
        self.assertTrue(by_name["Maya Chen"].eligible)
        self.assertEqual(by_name["Maya Chen"].eligibility_reasons, [])
        self.assertFalse(by_name["Owen Patel"].eligible)
        self.assertIn("Post-test score below 80%", by_name["Owen Patel"].eligibility_reasons)
        self.assertFalse(by_name["Nora Brooks"].eligible)
        self.assertIn("Missing or invalid email", by_name["Nora Brooks"].eligibility_reasons)

    def test_xlsx_upload_uses_same_row_matching_pipeline(self) -> None:
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.append(["Full Name", "Email", "Company"])
        worksheet.append(["Iris Stone", "iris.stone@example.com", "Summit Dealer"])
        output = BytesIO()
        workbook.save(output)

        rows = parse_xlsx_bytes(output.getvalue())
        self.assertEqual(rows[0]["Full Name"], "Iris Stone")

        row_count, errors = process_document(
            self.db,
            self.event_id,
            "registration",
            "registration.xlsx",
            output.getvalue(),
        )
        self.db.commit()
        self.assertEqual(row_count, 1)
        self.assertEqual(errors, [])
        link = self.db.scalar(select(EventAttendee).where(EventAttendee.event_id == self.event_id))
        self.assertIsNotNone(link)
        self.assertTrue(link.registered)

    def test_png_ocr_extracts_comma_separated_table_text(self) -> None:
        font = _fixture_font()
        image = Image.new("RGB", (1400, 220), "white")
        draw = ImageDraw.Draw(image)
        draw.text((30, 30), "Full Name | Email | Company", font=font, fill="black")
        draw.text(
            (30, 100),
            "Maya Chen | maya.chen@example.com | Northline",
            font=font,
            fill="black",
        )
        output = BytesIO()
        image.save(output, format="PNG")

        rows, warnings = parse_image_bytes(output.getvalue())
        self.assertGreaterEqual(len(warnings), 1)
        self.assertEqual(rows[0]["Full Name"], "Maya Chen")
        self.assertEqual(rows[0]["Email"], "maya.chen@example.com")

    def test_scanned_pdf_falls_back_to_embedded_image_ocr(self) -> None:
        # Scan-to-PDF: a page with no text layer, only an embedded photo of the
        # sign-in sheet. The PDF parser must OCR the embedded image.
        from reportlab.lib.utils import ImageReader
        from reportlab.pdfgen.canvas import Canvas

        font = _fixture_font()
        image = Image.new("RGB", (1400, 220), "white")
        draw = ImageDraw.Draw(image)
        draw.text((30, 30), "Full Name | Email | Company", font=font, fill="black")
        draw.text(
            (30, 100),
            "Maya Chen | maya.chen@example.com | Northline",
            font=font,
            fill="black",
        )

        output = BytesIO()
        canvas = Canvas(output, pagesize=(700, 110))
        canvas.drawImage(ImageReader(image), 0, 0, width=700, height=110)
        canvas.save()

        rows, warnings = parse_pdf_bytes(output.getvalue())
        self.assertTrue(any("best-effort" in w["message"] for w in warnings))
        self.assertEqual(rows[0]["Full Name"], "Maya Chen")
        self.assertEqual(rows[0]["Email"], "maya.chen@example.com")


if __name__ == "__main__":
    unittest.main()
