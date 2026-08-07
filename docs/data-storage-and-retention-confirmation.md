# Data Storage & Retention Confirmation

*Prepared for the CEU provider agreement — describes how attendee records and
certificates handled by the NMEDA training-event (CEU) portal are stored,
secured, and retained.*

---

**[PROVIDER LEGAL NAME]**
[Address line 1]
[City, State ZIP]

**Date:** [DATE]
**Re:** Secure storage and retention of attendee records — CEU Provider [PROVIDER / ACCOUNT NUMBER]
**To:** [ACCREDITING BODY / RECIPIENT NAME]

---

To whom it may concern,

This letter confirms how [PROVIDER LEGAL NAME] stores, protects, and retains the
attendee records and continuing-education certificates generated through our
online CEU training-event portal.

## 1. What data is stored

The portal stores, for each training event:

- Attendee sign-in sheets and rosters (may contain names, email addresses, and
  professional license information).
- Post-test and survey submissions.
- Generated continuing-education certificates, each bearing a unique
  certificate number.

## 2. Where and how it is stored

- **Records database:** attendee records, event details, and the immutable data
  used to generate each certificate are held in a managed PostgreSQL database
  hosted by Supabase.
- **Uploaded files and certificate PDFs:** stored as objects in a **private**
  Supabase Storage bucket. The bucket is configured as private — it is **not**
  publicly accessible and exposes no public/shareable links to any file.

## 3. How it is protected

- **Encryption in transit:** all connections to the portal and to the storage
  and database services use HTTPS/TLS. Data is encrypted while moving between
  the user's browser, the application, and the storage provider.
- **Encryption at rest:** files and database records are encrypted at rest by
  the hosting provider's infrastructure.
- **Access control:** stored files are served only through the application's
  authenticated endpoints. Access to attendee personal information and to the
  compliance-review function is restricted to authorized administrators.
  Instructors/presenters have a limited role and cannot view compliance records
  or other events' attendee data.
- **Privileged credentials** used by the application to reach the storage
  service are held server-side only and are never exposed in the browser or to
  end users.

## 4. Retention

- Attendee records and issued certificates are retained for **seven (7) years**
  from the date of the associated training event, consistent with our CEU
  provider obligations.
- Certificates are generated from an immutable snapshot of the attendee's
  record, so each issued certificate can be reproduced and verified for the full
  retention period.
- Records are securely deleted after the retention period has elapsed.

## 5. Current status of the production environment

The portal's data-protection design described above is in effect. We are in the
process of finalizing our migration to a hardened production hosting tier that
adds guaranteed point-in-time database backups, non-sleeping always-on
availability, and an encrypted persistent disk, to fully support the seven-year
retention commitment. This confirmation will be updated upon completion of that
migration.

Please contact the undersigned with any questions regarding our data handling
practices.

Sincerely,

<br>

_______________________________
**[SIGNATORY NAME]**
[Title]
[PROVIDER LEGAL NAME]
[Email] · [Phone]

---

*Fields in [BRACKETS] are to be completed before sending. See the accompanying
notes for what each safeguard means in plain terms.*
