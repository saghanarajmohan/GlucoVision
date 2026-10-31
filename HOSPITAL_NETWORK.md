# GlucoVision hospital network and safe demo reset

## Existing persistence inspected

The app uses SQLAlchemy with SQLite at `glucovision.db` in the repository root (`sqlite:///./glucovision.db`, relative to the working directory). FastAPI imports `Base.metadata.create_all()` and runs additive SQLite migrations in `backend/main.py`; there is no Alembic migration directory. Model weights and inference code live under `model/` and `backend/`. Screening uploads are temporary files and are removed after inference; the Grad-CAM preview is `gradcam_result.jpg`.

Existing tables and relationships:

- `users`: login hashes, role, optional `hospital_id` and `health_centre_id`.
- `hospitals` → `health_centres` (one hospital controls multiple centres); hospitals also relate to appointments.
- `health_centres` → patients, screenings, appointments and notifications.
- `patients` → screenings, appointments and notifications.
- `screenings` → patient and originating centre; each screening retains its own AI result, immutable routing snapshot, clinical review, retinal image, Grad-CAM output and original screening PDF.
- `appointments` → patient, screening (optional), hospital and originating centre.
- `notifications` → patient, appointment (optional), originating centre, and the hospital snapshot for oversight.
- `calendar_integrations`: existing local calendar token/sync state.
- `network_audits`: administrator assignment changes and hospital review actions.

The SQLite schema is retained during migrations and reset. The app enables SQLite foreign-key checks. Hospital and health-centre codes have unique indexes; assignment is a single nullable `health_centres.assigned_hospital_id` foreign key.

## Patient reports and original screening files

The health-centre history endpoint returns the saved patient demographics, AI prediction, confidence, class scores, referral and review state, and private asset links for each screening. The health-centre dashboard can expand that complete report and retrieve the original PDF after refresh or referral. Hospital cards use the same screening ID and authenticated PDF endpoint, so both roles receive the same stored PDF bytes. `X-Content-SHA256` is returned on file retrieval for integrity checks. Legacy screenings without a persisted PDF are reported as unavailable rather than silently regenerated.

New analyses generate Grad-CAM output into a unique per-request temporary path before copying it into the screening's private storage. They do not read a shared root-level `gradcam_result.jpg`, which could belong to another screening.

## Reset demonstration records (explicit, backup first)

Run these commands from the project root in Windows PowerShell, with the virtual environment active. Close the running backend first so no appointment worker is writing to SQLite.

```powershell
.\.venv\Scripts\Activate.ps1
python .\reset_demo_data.py
```

The script creates and integrity-checks `database_backups\glucovision-pre-reset-<timestamp>.db` before asking for the exact confirmation `RESET`. It then removes clinical/demo rows, demo hospital and centre rows, and non-super-admin demo accounts. It retains the SQLite file, all tables/schema, calendar integration configuration, source code, model files/weights and app configuration. If no super-admin exists, it securely prompts for a username and a password (12+ characters) twice and stores only the app's bcrypt hash. It does not expose a reset API and does not reset automatically at server startup.

To restore a backup, stop the backend, copy the chosen `.db` backup over `glucovision.db`, and restart the backend. Keep backups private; they contain patient and screening information.

## Create accounts

To create the first super-admin without resetting data:

```powershell
python .\create_super_admin.py
```

After creating hospitals and centres in the Super Admin dashboard, provision scoped accounts interactively:

```powershell
python .\create_network_user.py
```

Choose `HOSPITAL_ADMIN` or `HEALTH_CENTRE_STAFF`, then select the associated active record. Passwords are entered with a hidden prompt and bcrypt-hashed. There are no hardcoded credentials. Existing `DOCTOR` and `HEALTH_CENTRE` roles remain recognized for compatibility; newly provisioned accounts use the explicit role names.

## Run locally

From the repository root:

```powershell
.\.venv\Scripts\Activate.ps1
uvicorn backend.main:app --reload
```

In a second PowerShell window:

```powershell
cd .\frontend
npm run dev -- --host 127.0.0.1
```

Ensure `.env` contains a private, random `APP_SIGNING_SECRET` and the appointment settings. Do not commit `.env` or production secrets.

## Demonstration flow

1. Sign in as the super-admin. Add a uniquely coded hospital, then add multiple uniquely coded health centres and assign each to that hospital. Reassign or deactivate centres in the centre list; changes are audited.
2. Create scoped users with `create_network_user.py`. A hospital user can only read routed reports, centres, and missed-appointment notices for its own `hospital_id`; centre staff are limited to their `health_centre_id`.
3. Sign in at a health centre, register a patient, and run screening. The screening row snapshots the centre and its active assigned hospital when created. A report from an unassigned centre is retained with `AWAITING_ASSIGNMENT`; the Super Admin overview surfaces it. The original PDF and images are saved under report-ID-specific paths in private storage.
4. Refresh the health-centre dashboard and open the screening from patient history. Submit the referral, sign in as the assigned hospital, and open the same report card. Both dashboards use the same authenticated original-PDF route; downloads include a SHA-256 header.
5. Hospital cards list every screening for a patient, with stored AI scores and images. Review notes and urgent flags are stored separately from the AI prediction; the original prediction is returned unchanged.
6. Schedule an appointment in the past or wait until its configured end plus grace period. The existing scheduler marks it `MISSED` once, creates the local centre notification and snapshots the assigned hospital for oversight. Hospital follow-up notes persist in SQLite. The independent five-calendar-day alert uses the referral's `submitted_at` timestamp.
7. Reassign a centre and screen again. New reports route to the new hospital; already routed reports and notifications stay with their original hospital for audit.

Backend checks: `python -m unittest discover -s tests -v`. Frontend production build: from `frontend`, `npm run build`.
