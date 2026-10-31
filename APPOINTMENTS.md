# Local appointment workflow

GlucoVision appointments are stored in the existing SQLite `appointments` table. Health-centre users schedule from registered patients; the assigned hospital is taken from the health-centre relationship. No Google account, Calendar API, OAuth credentials, or network calendar access is used.

## Configuration

Copy `.env.example` to `.env`, then set a private `APP_SIGNING_SECRET` (for example, generate one with `python -c "import secrets; print(secrets.token_urlsafe(48))"`). Configure:

- `APP_TIMEZONE`: IANA clinic time zone, default `Asia/Kolkata`.
- `APPOINTMENT_DURATION_MINUTES`: appointment duration, default 30.
- `APPOINTMENT_GRACE_MINUTES`: grace period after the clinic-local appointment date ends, default 15 minutes. A scheduled appointment is not marked missed during its appointment date, regardless of the entered time.
- `APPOINTMENT_CHECK_INTERVAL_SECONDS`: backend check interval, default 60 (minimum 15).
- `REFERRAL_ATTENDANCE_FOLLOW_UP_DAYS`: referral attendance deadline in clinic-calendar days, default 5.
- `GLUCOVISION_PRIVATE_STORAGE_DIR`: private persistent storage for original reports and images, default `./private_storage`.

The backend rejects nonexistent or ambiguous clinic wall times around daylight-saving changes. Comparisons use UTC instants derived from the configured clinic time zone and the backend's UTC clock.

## Start

From the repository root, start the backend:

```powershell
.venv\Scripts\python.exe -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

In another terminal:

```powershell
cd frontend
npm run dev
```

The backend starts the appointment and referral scheduler as part of FastAPI lifespan, so it runs without a browser or logged-in user and stops with the application. It checks every `APPOINTMENT_CHECK_INTERVAL_SECONDS`. SQLite schema changes are applied additively when the backend starts. Existing appointment, patient, notification, and legacy integration rows are preserved; old Calendar-only columns and the old integration table remain inert in the database to avoid deleting existing data. Automatic processing requires the backend to remain running.

Hospital staff record physical attendance from the hospital dashboard using the report's **Record hospital attendance** action, or by marking the associated consultation completed. The system records the first hospital-attendance timestamp and resolves any existing referral or missed-consultation alerts without deleting their audit history. The five-day referral alert is independent of appointment scheduling and is based on `submitted_at`.

New screening originals are persisted under the private storage directory using report-ID-specific paths. The original PDF is generated once when the screening report is saved; hospitals and the originating centre access it through authenticated, organisation-scoped endpoints. The server returns a SHA-256 response header to support integrity checks. Do not place private storage under a web-served static directory or commit it to source control.

## Hospital patient categories

The hospital dashboard has four primary views: `New Referrals` includes the newest patient report without a saved care disposition; `Ongoing Care` includes explicit `FOLLOW_UP_REQUIRED` and `STABLE_MONITORING` decisions; `Completed` requires the explicit `DISCHARGED_CARE_COMPLETED` decision; and `Missed Appointments` lists each missed appointment with its original history and health-centre notification. A patient may appear in a care category and also have a missed appointment. Missing disposition or an AI screening result is never interpreted as recovery. Follow-up and stable monitoring reviews require a future appointment; completed care does not.

## Schedule and verify

1. Sign in as a health-centre user whose health-centre row has an assigned hospital.
2. Register or select a patient at that same centre.
3. Use **Schedule an appointment** to choose a clinic-local date/time and enter the follow-up reason. The patient's saved phone is used in the notification; it can be updated through the appointment API's optional `phone` field.
4. The dashboard lists recent appointments; staff can cancel a scheduled appointment. A cancelled appointment can be rescheduled through `PATCH /appointments/{id}`.
5. For a test, set a short grace period in `.env`, schedule an appointment for an earlier clinic-local date, then wait through the configured checker interval. The status becomes `MISSED` only after that date ends and the grace period passes; `missed_detected_at` is recorded in UTC, and one health-centre notification appears. Mark it acknowledged in the notification panel.
6. Run automated tests with `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_appointments.py"`.

The tests use temporary SQLite databases and fixed UTC instants; they do not need external credentials or network access. Keep the backend process running for automatic checks.
