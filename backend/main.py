import json
import os
import tempfile
import base64
import hashlib
import hmac
import logging
import shutil
import uuid
from pathlib import Path
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta

from fastapi import FastAPI, File, UploadFile, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel


def _load_environment_file():
    env_path = os.path.join(os.getcwd(), ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path, encoding="utf-8") as env_file:
        for line in env_file:
            item = line.strip()
            if not item or item.startswith("#") or "=" not in item:
                continue
            key, value = item.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_environment_file()

from backend.database import SessionLocal, engine, Base
from backend.models import (
    User,
    Hospital,
    HealthCentre,
    Patient,
    Screening,
    Appointment,
    Notification,
    NetworkAudit,
)
from backend.auth import verify_password
from backend.auth import hash_password
from backend.report_files import (
    private_storage_root,
    write_private_file,
    resolve_private_file,
    sha256_bytes,
    generate_original_screening_pdf,
)

from backend.ml_inference import run_inference
from backend.image_quality import check_image_quality
from backend.appointment_scheduler import (
    start_scheduler,
    stop_scheduler,
    clinic_local_datetime,
    clinic_timezone,
    process_missed_appointments,
)

logger = logging.getLogger(__name__)


def _migrate_clinical_dispositions(connection):
    """Map old disposition codes into separate, auditable disposition/outcome fields."""
    from sqlalchemy import text
    connection.execute(text("UPDATE screenings SET clinical_outcome='RECOVERED', clinical_disposition='DISCHARGED_CARE_COMPLETED', follow_up_required=0 WHERE clinical_disposition='RECOVERED' AND clinical_outcome IS NULL"))
    connection.execute(text("UPDATE screenings SET clinical_outcome='DISCHARGED_WITHOUT_DOCUMENTED_RECOVERY', clinical_disposition='DISCHARGED_CARE_COMPLETED', follow_up_required=0 WHERE clinical_disposition='DISCHARGED' AND clinical_outcome IS NULL"))
    connection.execute(text("UPDATE screenings SET clinical_disposition='FOLLOW_UP_REQUIRED', follow_up_required=1 WHERE clinical_disposition='FOLLOW_UP'"))
    # Legacy stable notes were free text and may not describe a monitoring plan.
    # Keep those records out of Follow-up Required until a clinician documents it.
    connection.execute(text("UPDATE screenings SET follow_up_required=0 WHERE clinical_disposition='STABLE_MONITORING' AND follow_up_required IS NULL"))


def _migrate_schema():
    """Small additive migration for existing SQLite installations."""
    from sqlalchemy import inspect, text
    inspector = inspect(engine)
    additions = {
        "users": {"is_active": "BOOLEAN NOT NULL DEFAULT 1"},
        "hospitals": {"code": "VARCHAR", "district": "VARCHAR", "state": "VARCHAR", "address": "TEXT", "contact_number": "VARCHAR", "official_email": "VARCHAR", "is_active": "BOOLEAN NOT NULL DEFAULT 1"},
        "health_centres": {"code": "VARCHAR", "district": "VARCHAR", "state": "VARCHAR", "address": "TEXT", "contact_number": "VARCHAR", "is_active": "BOOLEAN NOT NULL DEFAULT 1"},
        "patients": {"phone": "VARCHAR"},
        "appointments": {"missed_detected_at": "DATETIME", "appointment_end_datetime": "DATETIME"},
        "notifications": {
            "acknowledged_at": "DATETIME", "patient_phone": "VARCHAR", "appointment_time": "VARCHAR",
            "assigned_hospital_id": "INTEGER REFERENCES hospitals(id)", "hospital_follow_up": "TEXT", "hospital_follow_up_by": "INTEGER REFERENCES users(id)", "hospital_follow_up_at": "DATETIME",
            "referral_screening_id": "INTEGER REFERENCES screenings(id)", "resolved_at": "DATETIME", "resolved_by_user_id": "INTEGER REFERENCES users(id)",
        },
        "screenings": {"routed_hospital_id": "INTEGER REFERENCES hospitals(id)", "review_status": "VARCHAR NOT NULL DEFAULT 'PENDING'", "clinical_review_notes": "TEXT", "clinical_outcome": "VARCHAR", "follow_up_required": "BOOLEAN", "clinical_reviewer_id": "INTEGER REFERENCES users(id)", "clinical_reviewed_at": "DATETIME", "clinically_flagged": "BOOLEAN NOT NULL DEFAULT 0", "follow_up_priority": "VARCHAR", "clinical_disposition": "VARCHAR", "disposition_recorded_by": "INTEGER REFERENCES users(id)", "disposition_updated_at": "DATETIME", "routed_at": "DATETIME", "submitted_at": "DATETIME", "hospital_attended_at": "DATETIME", "hospital_attended_by": "INTEGER REFERENCES users(id)", "original_report_pdf_path": "VARCHAR", "original_heatmap_path": "VARCHAR"},
    }
    with engine.begin() as connection:
        for table, columns in additions.items():
            existing = {column["name"] for column in inspect(engine).get_columns(table)}
            for name, kind in columns.items():
                if name not in existing:
                    connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {kind}"))
        appointment_columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(appointments)").all()}
        if "calendar_end_at" in appointment_columns:
            connection.execute(text("UPDATE appointments SET appointment_end_datetime = calendar_end_at WHERE appointment_end_datetime IS NULL AND calendar_end_at IS NOT NULL"))
        notification_columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(notifications)").all()}
        if "appointment_calendar_time" in notification_columns:
            connection.execute(text("UPDATE notifications SET appointment_time = appointment_calendar_time WHERE appointment_time IS NULL AND appointment_calendar_time IS NOT NULL"))
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_notification_appointment_type ON notifications (appointment_id, notification_type)"))
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_hospitals_code ON hospitals (code) WHERE code IS NOT NULL"))
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_health_centres_code ON health_centres (code) WHERE code IS NOT NULL"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_users_hospital_id ON users (hospital_id)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_users_health_centre_id ON users (health_centre_id)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_screenings_submitted_at ON screenings (submitted_at)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_screenings_hospital_disposition ON screenings (routed_hospital_id, clinical_disposition)"))
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_notification_referral_screening_type ON notifications (referral_screening_id, notification_type) WHERE referral_screening_id IS NOT NULL"))
        connection.execute(text("UPDATE screenings SET submitted_at=COALESCE(routed_at, created_at) WHERE submitted_to_hospital='YES' AND submitted_at IS NULL"))
        # Preserve legacy decisions. The migration is additive and does not touch AI results or appointments.
        _migrate_clinical_dispositions(connection)
        connection.execute(text("UPDATE screenings SET routed_hospital_id=(SELECT assigned_hospital_id FROM health_centres WHERE health_centres.id=screenings.health_centre_id), review_status=CASE WHEN (SELECT assigned_hospital_id FROM health_centres WHERE health_centres.id=screenings.health_centre_id) IS NULL THEN 'AWAITING_ASSIGNMENT' ELSE 'PENDING' END, routed_at=created_at WHERE routed_hospital_id IS NULL"))
        connection.execute(text("UPDATE notifications SET assigned_hospital_id=(SELECT assigned_hospital_id FROM health_centres WHERE health_centres.id=notifications.health_centre_id) WHERE notification_type='MISSED_APPOINTMENT' AND assigned_hospital_id IS NULL"))
        # SQLite cannot drop NOT NULL in place. Preserve the complete legacy table and
        # its records/columns while making screening_id optional for routine visits.
        create_sql = connection.execute(text("SELECT sql FROM sqlite_master WHERE type='table' AND name='appointments'")).scalar()
        if create_sql and "screening_id INTEGER NOT NULL" in create_sql:
            indexes = connection.execute(text("SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name='appointments' AND sql IS NOT NULL")).scalars().all()
            temp_sql = create_sql.replace("CREATE TABLE appointments", "CREATE TABLE appointments_rebuild", 1).replace("screening_id INTEGER NOT NULL", "screening_id INTEGER", 1)
            connection.execute(text("PRAGMA foreign_keys=OFF"))
            connection.execute(text(temp_sql))
            columns = [row[1] for row in connection.exec_driver_sql("PRAGMA table_info(appointments)").all()]
            names = ", ".join(f'"{name}"' for name in columns)
            connection.execute(text(f"INSERT INTO appointments_rebuild ({names}) SELECT {names} FROM appointments"))
            connection.execute(text("DROP TABLE appointments"))
            connection.execute(text("ALTER TABLE appointments_rebuild RENAME TO appointments"))
            for sql in indexes:
                connection.execute(text(sql))


# ============================================================
# DATABASE
# ============================================================

if os.getenv("GLUCOVISION_SKIP_SCHEMA_INIT") != "1":
    Base.metadata.create_all(bind=engine)
    _migrate_schema()


# ============================================================
# FASTAPI APP
# ============================================================

@asynccontextmanager
async def lifespan(_app):
    start_scheduler()
    try:
        yield
    finally:
        stop_scheduler()


app = FastAPI(
    title="GlucoVision API",
    description="AI-assisted diabetic retinopathy screening backend",
    version="1.0.0",
    lifespan=lifespan,
)


def _session_token(user_id):
    expires = int(datetime.now(timezone.utc).timestamp()) + 60 * 60 * 12
    payload = f"{user_id}:{expires}"
    secret = os.getenv("APP_SIGNING_SECRET", "").encode()
    if not secret:
        raise HTTPException(status_code=503, detail="APP_SIGNING_SECRET is not configured")
    signature = hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{payload}:{signature}".encode()).decode()


def _authenticated_user(authorization, db):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Sign in required")
    try:
        decoded = base64.urlsafe_b64decode(authorization[7:].encode()).decode()
        user_id, expires, signature = decoded.split(":")
        payload = f"{user_id}:{expires}"
        expected = hmac.new(os.getenv("APP_SIGNING_SECRET", "").encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected) or int(expires) < int(datetime.now(timezone.utc).timestamp()):
            raise ValueError("Invalid or expired token")
        user = db.query(User).filter(User.id == int(user_id)).first()
        if not user:
            raise ValueError("Unknown user")
        if not user.is_active:
            raise HTTPException(status_code=403, detail="This account is disabled")
        role = user.role.upper()
        centre_roles = {"HEALTH_CENTRE", "HEALTH CENTRE", "HEALTH_CENTRE_USER", "HEALTH_CENTRE_STAFF"}
        if role in centre_roles and (not user.health_centre_id or user.hospital_id is not None):
            raise HTTPException(status_code=403, detail="Health-centre account scope is invalid")
        if role in {"HOSPITAL_ADMIN", "DOCTOR"} and (not user.hospital_id or user.health_centre_id is not None):
            raise HTTPException(status_code=403, detail="Hospital account scope is invalid")
        return user
    except (ValueError, TypeError):
        raise HTTPException(status_code=401, detail="Invalid or expired session")


# ============================================================
# CORS
# ============================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# ROOT
# ============================================================

@app.get("/")
def root():
    return {
        "message": "GlucoVision API is running"
    }


# ============================================================
# AUTHENTICATION
# ============================================================

class LoginRequest(BaseModel):
    username: str
    password: str


@app.post("/auth/login")
def login(request: LoginRequest):

    db = SessionLocal()

    try:

        user = (
            db.query(User)
            .filter(
                User.username == request.username
            )
            .first()
        )

        if not user:

            raise HTTPException(
                status_code=401,
                detail="Invalid username or password",
            )

        if not verify_password(
            request.password,
            user.password_hash,
        ):

            raise HTTPException(
                status_code=401,
                detail="Invalid username or password",
            )

        if not user.is_active:
            raise HTTPException(status_code=403, detail="This account is disabled")

        if user.role.upper() == "HOSPITAL_ADMIN" and not db.query(Hospital).filter_by(id=user.hospital_id, is_active=True).first():
            raise HTTPException(status_code=403, detail="This hospital account is inactive")
        if user.role.upper() in {"HEALTH_CENTRE", "HEALTH CENTRE", "HEALTH_CENTRE_USER", "HEALTH_CENTRE_STAFF"} and not db.query(HealthCentre).filter_by(id=user.health_centre_id, is_active=True).first():
            raise HTTPException(status_code=403, detail="This health-centre account is inactive")

        return {
            "message": "Login successful",
            "user_id": user.id,
            "name": user.name,
            "username": user.username,
            "role": user.role,
            "hospital_id": user.hospital_id,
            "health_centre_id": user.health_centre_id,
            "appointment_time_zone": os.getenv("APP_TIMEZONE", "Asia/Kolkata"),
            "session_token": _session_token(user.id),
        }

    finally:

        db.close()


def _authorize_screening_asset_access(user, screening, db):
    role = user.role.upper()
    if role in {"HEALTH_CENTRE", "HEALTH CENTRE", "HEALTH_CENTRE_USER", "HEALTH_CENTRE_STAFF"}:
        _require_health_centre_staff(user, screening.health_centre_id, db)
    elif role in {"HOSPITAL_ADMIN", "DOCTOR"}:
        _require_hospital_user(user, db)
        if screening.routed_hospital_id != user.hospital_id or screening.submitted_to_hospital != "YES":
            raise HTTPException(status_code=404, detail="Screening not found")
    elif role != "SUPER_ADMIN":
        raise HTTPException(status_code=403, detail="Screening access is restricted")


def _screening_asset_response(db, screening_id, authorization, asset_field, media_type, filename):
    user = _authenticated_user(authorization, db)
    screening = db.query(Screening).filter_by(id=screening_id).first()
    if not screening:
        raise HTTPException(status_code=404, detail="Screening not found")
    _authorize_screening_asset_access(user, screening, db)
    asset = resolve_private_file(getattr(screening, asset_field))
    if not asset:
        raise HTTPException(status_code=404, detail="The original screening file is not available")
    content = asset.read_bytes()
    return Response(content=content, media_type=media_type, headers={
        "Content-Disposition": f'inline; filename="{filename}"',
        "Cache-Control": "private, no-store",
        "X-Content-SHA256": sha256_bytes(content),
    })


@app.get("/screening/{screening_id}/original-pdf")
def get_original_screening_pdf(screening_id: int, authorization: str | None = Header(default=None)):
    db = SessionLocal()
    try:
        return _screening_asset_response(db, screening_id, authorization, "original_report_pdf_path",
            "application/pdf", f"GlucoVision_Screening_Report_{screening_id}.pdf")
    finally:
        db.close()


@app.get("/screening/{screening_id}/original-image")
def get_original_screening_image(screening_id: int, authorization: str | None = Header(default=None)):
    import mimetypes
    db = SessionLocal()
    try:
        user = _authenticated_user(authorization, db)
        screening = db.query(Screening).filter_by(id=screening_id).first()
        if not screening:
            raise HTTPException(status_code=404, detail="Screening not found")
        _authorize_screening_asset_access(user, screening, db)
        asset = resolve_private_file(screening.retinal_image_path)
        if not asset:
            raise HTTPException(status_code=404, detail="The original retinal image is not available")
        content = asset.read_bytes()
        return Response(content=content, media_type=mimetypes.guess_type(asset.name)[0] or "application/octet-stream",
            headers={"Cache-Control": "private, no-store", "X-Content-SHA256": sha256_bytes(content)})
    finally:
        db.close()


@app.get("/screening/{screening_id}/heatmap")
def get_screening_heatmap(screening_id: int, authorization: str | None = Header(default=None)):
    db = SessionLocal()
    try:
        return _screening_asset_response(db, screening_id, authorization, "original_heatmap_path",
            "image/jpeg", f"GlucoVision_GradCAM_{screening_id}.jpg")
    finally:
        db.close()


# ============================================================
# PATIENT REGISTRATION
# ============================================================

class PatientCreate(BaseModel):
    name: str
    age: int
    sex: str
    phone: str | None = None


def _require_health_centre_staff(user, health_centre_id, db=None):
    roles = {"HEALTH_CENTRE", "HEALTH CENTRE", "HEALTH_CENTRE_USER", "HEALTH_CENTRE_STAFF"}
    if user.role.upper() not in roles or user.health_centre_id != health_centre_id:
        raise HTTPException(status_code=403, detail="This operation is restricted to your assigned health centre")
    if db is not None and not db.query(HealthCentre.id).filter_by(id=health_centre_id, is_active=True).first():
        raise HTTPException(status_code=403, detail="Health-centre account is inactive")


def _route_screening(db, screening):
    """Snapshot the centre's current hospital so later reassignment cannot rewrite history."""
    centre = db.query(HealthCentre).filter(HealthCentre.id == screening.health_centre_id).first()
    hospital = db.query(Hospital).filter(Hospital.id == centre.assigned_hospital_id, Hospital.is_active.is_(True)).first() if centre and centre.assigned_hospital_id else None
    screening.routed_hospital_id = hospital.id if hospital else None
    screening.review_status = "PENDING" if screening.routed_hospital_id else "AWAITING_ASSIGNMENT"
    screening.routed_at = datetime.utcnow() if screening.routed_hospital_id else None
    return screening


def _appointment_end_utc(start_local):
    duration = timedelta(minutes=int(os.getenv("APPOINTMENT_DURATION_MINUTES", "30")))
    return (start_local.replace(tzinfo=clinic_timezone()).astimezone(timezone.utc) + duration).replace(tzinfo=None)


@app.get("/patients")
def list_patients(health_centre_id: int, authorization: str | None = Header(default=None)):
    db = SessionLocal()
    try:
        user = _authenticated_user(authorization, db)
        _require_health_centre_staff(user, health_centre_id, db)
        rows = db.query(Patient).filter(Patient.health_centre_id == health_centre_id).order_by(Patient.name).all()
        return {"patients": [{"id": p.id, "patient_code": p.patient_code, "name": p.name,
            "age": p.age, "sex": p.sex, "phone": p.phone, "created_at": p.created_at,
            "health_centre_id": p.health_centre_id} for p in rows]}
    finally:
        db.close()


@app.post("/patients")
def create_patient(
    patient_data: PatientCreate,
    health_centre_id: int,
    authorization: str | None = Header(default=None),
):

    db = SessionLocal()

    try:

        user = _authenticated_user(authorization, db)
        _require_health_centre_staff(user, health_centre_id, db)

        health_centre = (
            db.query(HealthCentre)
            .filter(
                HealthCentre.id == health_centre_id
            )
            .first()
        )

        if not health_centre:

            raise HTTPException(
                status_code=404,
                detail="Health centre not found",
            )

        patient_count = (
            db.query(Patient).count()
        )

        patient_code = (
            f"GV-{patient_count + 1:05d}"
        )

        patient = Patient(
            patient_code=patient_code,
            name=patient_data.name,
            age=patient_data.age,
            sex=patient_data.sex,
            phone=patient_data.phone,
            health_centre_id=health_centre_id,
        )

        db.add(patient)

        db.commit()

        db.refresh(patient)

        return {
            "message": "Patient registered successfully",
            "patient_id": patient.id,
            "patient_code": patient.patient_code,
            "name": patient.name,
            "age": patient.age,
            "sex": patient.sex,
            "health_centre_id": patient.health_centre_id,
        }

    finally:

        db.close()


# ============================================================
# AI PREDICTION
# ============================================================

@app.post("/predict")
async def predict(
    file: UploadFile = File(...),
    patient_id: int | None = None,
    authorization: str | None = Header(default=None),
):

    suffix = os.path.splitext(
        file.filename
    )[1]

    with tempfile.NamedTemporaryFile(
        delete=False,
        suffix=suffix,
    ) as temp_file:

        contents = await file.read()

        temp_file.write(contents)

        temp_path = temp_file.name

    try:

        # ----------------------------------------------------
        # IMAGE QUALITY CHECK
        # ----------------------------------------------------

        quality_result = check_image_quality(
            temp_path
        )

        if not quality_result["valid"]:

            return {
                "status": "rejected",
                "reason": quality_result["reason"],
            }

        # ----------------------------------------------------
        # AI INFERENCE
        # ----------------------------------------------------

        generated_heatmap_path = str(Path(temp_path).with_name(f"{Path(temp_path).stem}_gradcam.jpg"))
        result = run_inference(
            temp_path,
            heatmap_path=generated_heatmap_path,
        )

        # ----------------------------------------------------
        # GRAD-CAM
        # ----------------------------------------------------

        heatmap_source = Path(result.get("heatmap_path") or "")
        if not heatmap_source.is_file():
            heatmap_source = None

        # ----------------------------------------------------
        # SAVE SCREENING
        # ----------------------------------------------------

        if patient_id is not None:

            db = SessionLocal()

            try:

                current_user = _authenticated_user(authorization, db)
                if current_user.role.upper() not in {"HEALTH_CENTRE", "HEALTH CENTRE", "HEALTH_CENTRE_USER", "HEALTH_CENTRE_STAFF"} or not current_user.health_centre_id:
                    raise HTTPException(status_code=403, detail="Only assigned health-centre staff can create screenings")
                if not db.query(HealthCentre.id).filter_by(id=current_user.health_centre_id, is_active=True).first():
                    raise HTTPException(status_code=403, detail="Health-centre account is inactive")

                patient = (
                    db.query(Patient)
                    .filter(
                        Patient.id == patient_id,
                        Patient.health_centre_id == current_user.health_centre_id,
                    )
                    .first()
                )

                if patient:

                    probabilities = (
                        result.get(
                            "probabilities",
                            {},
                        )
                    )

                    prediction = (
                        result.get(
                            "prediction"
                        )
                    )

                    confidence = (
                        result.get(
                            "confidence"
                        )
                    )

                    screening = Screening(
                        patient_id=patient.id,

                        health_centre_id=(
                            patient.health_centre_id
                        ),

                        retinal_image_path=None,

                        prediction=prediction,

                        confidence=(
                            str(confidence)
                            if confidence is not None
                            else None
                        ),

                        probabilities=json.dumps(
                            probabilities
                        ),

                        gradcam_image_path=None,

                        status="SCREENED",

                        submitted_to_hospital="NO",

                        consulted_doctor=None,

                        doctor_notes=None,
                    )

                    _route_screening(db, screening)

                    db.add(screening)
                    db.flush()

                    file_suffix = Path(file.filename or "").suffix.lower()
                    if file_suffix not in {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}:
                        file_suffix = ".img"
                    image_relative = f"screenings/{screening.id}/retinal_image{file_suffix}"
                    screening.retinal_image_path = write_private_file(image_relative, Path(temp_path).read_bytes())

                    heatmap_relative = None
                    heatmap_file = None
                    if heatmap_source is not None:
                        heatmap_relative = f"screenings/{screening.id}/gradcam.jpg"
                        screening.original_heatmap_path = write_private_file(heatmap_relative, heatmap_source.read_bytes())
                        heatmap_file = resolve_private_file(screening.original_heatmap_path)

                    screening.gradcam_image_path = f"/screening/{screening.id}/heatmap"
                    pdf_bytes = generate_original_screening_pdf(
                        patient=patient,
                        centre=db.query(HealthCentre).filter_by(id=patient.health_centre_id).first(),
                        screening=screening,
                        image_path=resolve_private_file(screening.retinal_image_path),
                        heatmap_path=heatmap_file,
                    )
                    screening.original_report_pdf_path = write_private_file(
                        f"screenings/{screening.id}/original_report.pdf", pdf_bytes)
                    db.commit()

                    db.refresh(screening)

                    result["screening_id"] = (
                        screening.id
                    )

                    result["patient_id"] = (
                        patient.id
                    )

                    result["patient_code"] = (
                        patient.patient_code
                    )

                    result["patient_name"] = (
                        patient.name
                    )

                    result["heatmap_path"] = screening.gradcam_image_path
                    result["gradcam_image_path"] = screening.gradcam_image_path
                    result["original_report_pdf_path"] = f"/screening/{screening.id}/original-pdf"

            finally:

                db.close()

        return result

    finally:

        if os.path.exists(temp_path):

            os.remove(temp_path)
        if "generated_heatmap_path" in locals() and os.path.exists(generated_heatmap_path):
            os.remove(generated_heatmap_path)


# ============================================================
# SUBMIT SCREENING TO HOSPITAL
# ============================================================

@app.post(
    "/screening/{screening_id}/submit"
)
def submit_screening(
    screening_id: int,
    authorization: str | None = Header(default=None),
):

    db = SessionLocal()

    try:

        user = _authenticated_user(authorization, db)

        screening = (
            db.query(Screening)
            .filter(
                Screening.id == screening_id
            )
            .first()
        )

        if not screening:

            raise HTTPException(
                status_code=404,
                detail="Screening not found",
            )

        if user.role.upper() not in {"HEALTH_CENTRE", "HEALTH CENTRE", "HEALTH_CENTRE_USER", "HEALTH_CENTRE_STAFF"} or user.health_centre_id != screening.health_centre_id:
            raise HTTPException(status_code=403, detail="You cannot submit this screening")

        # ----------------------------------------------------
        # NO DIABETIC RETINOPATHY
        # ----------------------------------------------------
        # Patients with no DR should not be referred
        # to the hospital through this workflow.
        # ----------------------------------------------------

        prediction_text = (
            str(
                screening.prediction or ""
            )
            .strip()
            .lower()
        )

        if (
            "no diabetic retinopathy"
            in prediction_text
        ):

            raise HTTPException(
                status_code=400,
                detail=(
                    "Hospital referral is not required "
                    "for No Diabetic Retinopathy cases."
                ),
            )

        # ----------------------------------------------------
        # ONLY SUBMITTED CASES APPEAR IN SUBMITTED CASES
        # ----------------------------------------------------

        screening.status = "SUBMITTED"

        screening.submitted_to_hospital = "YES"
        if screening.submitted_at is None:
            screening.submitted_at = datetime.utcnow()

        db.commit()

        db.refresh(screening)

        return {
            "message": (
                "Screening submitted to hospital "
                "successfully"
            ),
            "screening_id": screening.id,
            "patient_id": screening.patient_id,
            "status": screening.status,
            "submitted_to_hospital": (
                screening.submitted_to_hospital
            ),
            "submitted_at": screening.submitted_at,
        }

    finally:

        db.close()


# ============================================================
# HELPER - FORMAT APPOINTMENT
# ============================================================

class LocalAppointmentCreate(BaseModel):
    patient_id: int
    appointment_datetime: datetime
    appointment_type: str = "Follow-up"
    notes: str | None = None
    phone: str | None = None


@app.post("/appointments")
def create_local_appointment(payload: LocalAppointmentCreate, authorization: str | None = Header(default=None)):
    db = SessionLocal()
    try:
        user = _authenticated_user(authorization, db)
        if user.role.upper() not in {"HEALTH_CENTRE", "HEALTH CENTRE", "HEALTH_CENTRE_USER", "HEALTH_CENTRE_STAFF"} or not user.health_centre_id:
            raise HTTPException(status_code=403, detail="Only health-centre staff can schedule appointments")
        if not db.query(HealthCentre.id).filter_by(id=user.health_centre_id, is_active=True).first():
            raise HTTPException(status_code=403, detail="Health-centre account is inactive")
        patient = db.query(Patient).filter(Patient.id == payload.patient_id, Patient.health_centre_id == user.health_centre_id).first()
        if not patient:
            raise HTTPException(status_code=404, detail="Patient not found at your health centre")
        centre = db.query(HealthCentre).filter(HealthCentre.id == user.health_centre_id).first()
        if not centre or not centre.assigned_hospital_id:
            raise HTTPException(status_code=409, detail="Assign a hospital to this health centre before scheduling")
        when = payload.appointment_datetime
        # datetime-local values are interpreted in configured clinic time. Persist the wall
        # time consistently with legacy appointments; the scheduler applies this IANA zone.
        try:
            when = clinic_local_datetime(when)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        appt = Appointment(
            screening_id=None, patient_id=patient.id, hospital_id=centre.assigned_hospital_id,
            health_centre_id=centre.id, doctor_name=user.name, appointment_datetime=when,
            appointment_end_datetime=_appointment_end_utc(when),
            appointment_type=payload.appointment_type.strip() or "Follow-up", notes=payload.notes,
            status="SCHEDULED",
        )
        if payload.phone and payload.phone.strip():
            patient.phone = payload.phone.strip()
        db.add(appt)
        db.commit()
        db.refresh(appt)
        # Run the same idempotent processor used by the background scheduler so
        # appointments whose clinic-local date and configured grace have passed are visible
        # as MISSED immediately. If processing is temporarily unavailable, the
        # saved appointment remains durable and the scheduler will retry it.
        try:
            process_missed_appointments()
            db.refresh(appt)
        except Exception:
            logger.exception("Immediate missed-appointment processing failed for appointment %s", appt.id)
        return {
            "message": "Appointment missed" if appt.status == "MISSED" else "Appointment scheduled",
            "appointment": format_appointment(appt),
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        logger.exception("Appointment creation failed")
        raise HTTPException(status_code=500, detail="Unable to create appointment")
    finally:
        db.close()


@app.get("/appointments")
def list_local_appointments(authorization: str | None = Header(default=None)):
    db = SessionLocal()
    try:
        user = _authenticated_user(authorization, db)
        if user.role.upper() not in {"HEALTH_CENTRE", "HEALTH CENTRE", "HEALTH_CENTRE_USER", "HEALTH_CENTRE_STAFF"} or not user.health_centre_id:
            raise HTTPException(status_code=403, detail="Appointment access is restricted")
        if not db.query(HealthCentre.id).filter_by(id=user.health_centre_id, is_active=True).first():
            raise HTTPException(status_code=403, detail="Health-centre account is inactive")
        rows = db.query(Appointment).filter(Appointment.health_centre_id == user.health_centre_id).order_by(Appointment.appointment_datetime.desc()).limit(200).all()
        return {"appointments": [{**format_appointment(a), "patient_name": a.patient.name, "patient_code": a.patient.patient_code, "patient_phone": a.patient.phone} for a in rows]}
    finally:
        db.close()


class AppointmentUpdate(BaseModel):
    appointment_datetime: datetime | None = None
    appointment_type: str | None = None
    notes: str | None = None
    status: str | None = None


@app.patch("/appointments/{appointment_id}")
def update_local_appointment(appointment_id: int, payload: AppointmentUpdate, authorization: str | None = Header(default=None)):
    db = SessionLocal()
    try:
        user = _authenticated_user(authorization, db)
        appt = db.query(Appointment).filter(Appointment.id == appointment_id).first()
        if not appt:
            raise HTTPException(status_code=404, detail="Appointment not found")
        _require_health_centre_staff(user, appt.health_centre_id, db)
        if appt.status not in {"SCHEDULED", "CANCELLED"}:
            raise HTTPException(status_code=409, detail="Only scheduled appointments can be changed")
        if payload.status is not None:
            if payload.status.upper() != "CANCELLED":
                raise HTTPException(status_code=400, detail="Only cancellation is supported here")
            appt.status = "CANCELLED"
        if payload.appointment_datetime is not None:
            try:
                when = clinic_local_datetime(payload.appointment_datetime)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc))
            appt.appointment_datetime = when
            appt.appointment_end_datetime = _appointment_end_utc(when)
            if appt.status == "CANCELLED":
                appt.status = "SCHEDULED"
        if payload.appointment_type is not None:
            appt.appointment_type = payload.appointment_type
        if payload.notes is not None:
            appt.notes = payload.notes
        appt.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(appt)
        return {"appointment": format_appointment(appt)}
    except HTTPException:
        db.rollback()
        raise
    finally:
        db.close()

def format_appointment(appointment):

    if not appointment:
        return None

    return {
        "id": appointment.id,

        "appointment_datetime": (
            appointment.appointment_datetime.replace(tzinfo=clinic_timezone()).isoformat()
            if appointment.appointment_datetime
            else None
        ),

        "appointment_end_datetime": (
            appointment.appointment_end_datetime.replace(tzinfo=timezone.utc).astimezone(clinic_timezone()).isoformat()
            if appointment.appointment_end_datetime else None
        ),

        "appointment_time_zone": os.getenv("APP_TIMEZONE", "Asia/Kolkata"),

        "appointment_type": (
            appointment.appointment_type
        ),

        "doctor_name": (
            appointment.doctor_name
        ),

        "status": (
            appointment.status
        ),

        "notes": (
            appointment.notes
        ),
    }


# ============================================================
# HOSPITAL CASES
# ============================================================

@app.get("/hospital/cases")
def get_hospital_cases(
    category: str | None = None,
    authorization: str | None = Header(default=None),
):

    db = SessionLocal()

    try:

        user = _authenticated_user(authorization, db)
        _require_hospital_user(user, db)

        screenings = (
            db.query(Screening)
            .filter(
                Screening.routed_hospital_id == user.hospital_id,
                Screening.submitted_to_hospital == "YES",
            )
            .order_by(
                Screening.id.desc()
            )
            .all()
        )

        cases = []

        for screening in screenings:

            patient = (
                db.query(Patient)
                .filter(
                    Patient.id
                    == screening.patient_id
                )
                .first()
            )

            health_centre = (
                db.query(HealthCentre)
                .filter(
                    HealthCentre.id
                    == screening.health_centre_id
                )
                .first()
            )

            # ------------------------------------------------
            # LATEST APPOINTMENT
            # ------------------------------------------------

            appointment = (
                db.query(Appointment)
                .filter(
                    Appointment.screening_id
                    == screening.id
                )
                .order_by(
                    Appointment.id.desc()
                )
                .first()
            )

            # ------------------------------------------------
            # CATEGORY FILTER
            # ------------------------------------------------
            #
            # submitted:
            #     waiting for doctor review
            #
            # reviewed:
            #     appointment attended
            #
            # followups:
            #     appointment scheduled
            #
            # ------------------------------------------------

            if category == "submitted":

                if screening.status != "SUBMITTED":
                    continue

            elif category == "reviewed":

                if (
                    not appointment
                    or appointment.status != "ATTENDED"
                ):
                    continue

            elif category == "followups":

                if (
                    not appointment
                    or appointment.status != "SCHEDULED"
                ):
                    continue

            cases.append(
                {
                    "screening_id": (
                        screening.id
                    ),

                    "patient_id": (
                        screening.patient_id
                    ),

                    "patient_code": (
                        patient.patient_code
                        if patient
                        else None
                    ),

                    "patient_name": (
                        patient.name
                        if patient
                        else None
                    ),

                    "age": (
                        patient.age
                        if patient
                        else None
                    ),

                    "sex": (
                        patient.sex
                        if patient
                        else None
                    ),

                    "health_centre": (
                        health_centre.name
                        if health_centre
                        else None
                    ),

                    "health_centre_id": (
                        screening.health_centre_id
                    ),

                    "prediction": (
                        screening.prediction
                    ),

                    "confidence": (
                        screening.confidence
                    ),

                    "probabilities": (
                        json.loads(
                            screening.probabilities
                        )
                        if screening.probabilities
                        else {}
                    ),

                    "gradcam_image_path": (
                        screening.gradcam_image_path
                    ),

                    "status": (
                        screening.status
                    ),

                    "submitted_to_hospital": (
                        screening.submitted_to_hospital
                    ),

                    "consulted_doctor": (
                        screening.consulted_doctor
                    ),

                    "doctor_notes": (
                        screening.doctor_notes
                    ),

                    "created_at": (
                        screening.created_at
                    ),

                    "appointment": (
                        format_appointment(
                            appointment
                        )
                    ),
                }
            )

        return {
            "category": category or "all",
            "total_cases": len(cases),
            "cases": cases,
        }

    finally:

        db.close()


# ============================================================
# DOCTOR REVIEW + APPOINTMENT
# ============================================================

class DoctorReviewRequest(BaseModel):

    consulted_doctor: str

    doctor_notes: str | None = None

    clinical_review_notes: str | None = None

    clinically_flagged: bool = False

    appointment_datetime: datetime | None = None

    appointment_type: str | None = (
        "Hospital Consultation"
    )


@app.post(
    "/screening/{screening_id}/review"
)
def review_screening(
    screening_id: int,
    review: DoctorReviewRequest,
    authorization: str | None = Header(default=None),
):

    db = SessionLocal()

    try:

        user = _authenticated_user(authorization, db)
        _require_hospital_user(user, db)

        screening = (
            db.query(Screening)
            .filter(
                Screening.id == screening_id,
                Screening.routed_hospital_id == user.hospital_id,
                Screening.submitted_to_hospital == "YES",
            )
            .first()
        )

        if not screening:

            raise HTTPException(
                status_code=404,
                detail="Screening not found",
            )

        # ----------------------------------------------------
        # SAVE DOCTOR CONSULTATION
        # ----------------------------------------------------

        screening.consulted_doctor = (
            review.consulted_doctor
        )

        screening.doctor_notes = (
            review.doctor_notes
        )
        if review.clinical_review_notes is not None:
            screening.clinical_review_notes = review.clinical_review_notes
        screening.clinically_flagged = review.clinically_flagged
        screening.clinical_reviewer_id = user.id
        screening.clinical_reviewed_at = datetime.utcnow()
        screening.review_status = "REVIEWED"

        # ----------------------------------------------------
        # HOSPITAL REVIEW COMPLETE
        # ----------------------------------------------------

        screening.status = "REVIEWED"

        # ----------------------------------------------------
        # APPOINTMENT
        # ----------------------------------------------------

        appointment = None

        if review.appointment_datetime:

            try:
                scheduled_when = clinic_local_datetime(review.appointment_datetime)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc))

            patient = (
                db.query(Patient)
                .filter(
                    Patient.id
                    == screening.patient_id
                )
                .first()
            )

            if not patient:

                raise HTTPException(
                    status_code=404,
                    detail="Patient not found",
                )

            health_centre = (
                db.query(HealthCentre)
                .filter(
                    HealthCentre.id
                    == screening.health_centre_id
                )
                .first()
            )

            if not health_centre:

                raise HTTPException(
                    status_code=404,
                    detail="Health centre not found",
                )

            if health_centre.assigned_hospital_id != user.hospital_id:
                raise HTTPException(status_code=409, detail="This health centre is no longer assigned to your hospital")

            if scheduled_when <= datetime.now(clinic_timezone()).replace(tzinfo=None):
                raise HTTPException(status_code=422, detail="Consultation must be scheduled in the future")

            hospital_id = user.hospital_id

            if not hospital_id:

                raise HTTPException(
                    status_code=400,
                    detail=(
                        "No hospital is assigned "
                        "to this health centre"
                    ),
                )

            # ------------------------------------------------
            # FIND LATEST SCHEDULED APPOINTMENT
            # ------------------------------------------------

            existing_appointment = (
                db.query(Appointment)
                .filter(
                    Appointment.screening_id
                    == screening.id
                )
                .filter(Appointment.hospital_id == user.hospital_id)
                .filter(
                    Appointment.status
                    == "SCHEDULED"
                )
                .order_by(
                    Appointment.id.desc()
                )
                .first()
            )

            if existing_appointment:

                existing_appointment.doctor_name = (
                    review.consulted_doctor
                )

                existing_appointment.appointment_datetime = (
                    scheduled_when
                )

                existing_appointment.appointment_end_datetime = _appointment_end_utc(scheduled_when)

                existing_appointment.appointment_type = (
                    review.appointment_type
                    or "Hospital Consultation"
                )

                existing_appointment.notes = (
                    review.doctor_notes
                )

                existing_appointment.updated_at = (
                    datetime.utcnow()
                )

                appointment = (
                    existing_appointment
                )

            else:

                appointment = Appointment(

                    screening_id=screening.id,

                    patient_id=screening.patient_id,

                    hospital_id=hospital_id,

                    health_centre_id=(
                        screening.health_centre_id
                    ),

                    doctor_name=(
                        review.consulted_doctor
                    ),

                    appointment_datetime=(
                        scheduled_when
                    ),

                    appointment_end_datetime=_appointment_end_utc(scheduled_when),

                    appointment_type=(
                        review.appointment_type
                        or "Hospital Consultation"
                    ),

                    status="SCHEDULED",

                    notes=review.doctor_notes,
                )

                db.add(appointment)

        # ----------------------------------------------------
        # SAVE EVERYTHING
        # ----------------------------------------------------

        db.commit()

        db.refresh(screening)

        if appointment:

            db.refresh(appointment)

        # ----------------------------------------------------
        # RESPONSE
        # ----------------------------------------------------

        return {
            "message": (
                "Doctor consultation saved successfully"
            ),

            "screening_id": (
                screening.id
            ),

            "consulted_doctor": (
                screening.consulted_doctor
            ),

            "doctor_notes": (
                screening.doctor_notes
            ),

            "status": (
                screening.status
            ),

            "review_status": screening.review_status,

            "clinical_review_notes": screening.clinical_review_notes,

            "clinical_disposition": screening.clinical_disposition,

            "clinical_outcome": screening.clinical_outcome,

            "follow_up_required": screening.follow_up_required,

            "clinically_flagged": screening.clinically_flagged,

            "appointment": (
                format_appointment(
                    appointment
                )
            ),
        }

    finally:

        db.close()


# ============================================================
# GET SINGLE SCREENING
# ============================================================

@app.get(
    "/screening/{screening_id}"
)
def get_screening(
    screening_id: int,
    authorization: str | None = Header(default=None),
):

    db = SessionLocal()

    try:

        user = _authenticated_user(authorization, db)

        screening = (
            db.query(Screening)
            .filter(
                Screening.id == screening_id
            )
            .first()
        )

        if not screening:

            raise HTTPException(
                status_code=404,
                detail="Screening not found",
            )

        role = user.role.upper()
        if role in {"HEALTH_CENTRE", "HEALTH CENTRE", "HEALTH_CENTRE_USER", "HEALTH_CENTRE_STAFF"}:
            _require_health_centre_staff(user, screening.health_centre_id, db)
        elif role in {"HOSPITAL_ADMIN", "DOCTOR"}:
            _require_hospital_user(user, db)
            if screening.routed_hospital_id != user.hospital_id or screening.submitted_to_hospital != "YES":
                raise HTTPException(status_code=404, detail="Screening not found")
        elif role != "SUPER_ADMIN":
            raise HTTPException(status_code=403, detail="Screening access is restricted")

        patient = (
            db.query(Patient)
            .filter(
                Patient.id
                == screening.patient_id
            )
            .first()
        )

        health_centre = (
            db.query(HealthCentre)
            .filter(
                HealthCentre.id
                == screening.health_centre_id
            )
            .first()
        )

        # ----------------------------------------------------
        # GET LATEST APPOINTMENT
        # ----------------------------------------------------

        appointment_query = db.query(Appointment).filter(Appointment.screening_id == screening.id)
        if role in {"HOSPITAL_ADMIN", "DOCTOR"}:
            appointment_query = appointment_query.filter(Appointment.hospital_id == user.hospital_id)
        elif role in {"HEALTH_CENTRE", "HEALTH CENTRE", "HEALTH_CENTRE_USER", "HEALTH_CENTRE_STAFF"}:
            appointment_query = appointment_query.filter(Appointment.health_centre_id == user.health_centre_id)
        appointment = appointment_query.order_by(Appointment.id.desc()).first()

        return {
            "screening_id": (
                screening.id
            ),

            "patient_id": (
                screening.patient_id
            ),

            "patient_code": (
                patient.patient_code
                if patient
                else None
            ),

            "patient_name": (
                patient.name
                if patient
                else None
            ),

            "age": (
                patient.age
                if patient
                else None
            ),

            "sex": (
                patient.sex
                if patient
                else None
            ),

            "health_centre": (
                health_centre.name
                if health_centre
                else None
            ),

            "prediction": (
                screening.prediction
            ),

            "confidence": (
                screening.confidence
            ),

            "probabilities": (
                json.loads(
                    screening.probabilities
                )
                if screening.probabilities
                else {}
            ),

            "gradcam_image_path": f"/screening/{screening.id}/heatmap" if screening.original_heatmap_path else None,

            "status": (
                screening.status
            ),

            "review_status": screening.review_status,

            "clinical_review_notes": screening.clinical_review_notes,

            "clinically_flagged": screening.clinically_flagged,

            "submitted_to_hospital": (
                screening.submitted_to_hospital
            ),

            "consulted_doctor": (
                screening.consulted_doctor
            ),

            "doctor_notes": (
                screening.doctor_notes
            ),

            "created_at": (
                screening.created_at
            ),

            "appointment": (
                format_appointment(
                    appointment
                )
            ),
        }

    finally:

        db.close()


# ============================================================
# MARK APPOINTMENT AS ATTENDED
# ============================================================

@app.post(
    "/appointments/{appointment_id}/attended"
)
def mark_appointment_attended(
    appointment_id: int,
    authorization: str | None = Header(default=None),
):

    db = SessionLocal()

    try:

        user = _authenticated_user(authorization, db)

        appointment = (
            db.query(Appointment)
            .filter(
                Appointment.id == appointment_id
            )
            .first()
        )

        if not appointment:

            raise HTTPException(
                status_code=404,
                detail="Appointment not found",
            )

        role = user.role.upper()
        if role in {"HEALTH_CENTRE", "HEALTH CENTRE", "HEALTH_CENTRE_USER", "HEALTH_CENTRE_STAFF"}:
            raise HTTPException(status_code=403, detail="Only authorised hospital staff can record hospital attendance")
        elif role in {"DOCTOR", "HOSPITAL_ADMIN"}:
            if not user.hospital_id or user.hospital_id != appointment.hospital_id:
                raise HTTPException(status_code=403, detail="You cannot update this appointment")
        elif role != "SUPER_ADMIN":
            raise HTTPException(status_code=403, detail="You cannot update this appointment")

        # ----------------------------------------------------
        # MARK APPOINTMENT AS ATTENDED
        # ----------------------------------------------------

        if appointment.status not in {"SCHEDULED", "MISSED"}:
            raise HTTPException(status_code=409, detail="Only scheduled or missed consultations can be marked attended")

        attended_at = datetime.utcnow()
        appointment.status = "ATTENDED"
        appointment.updated_at = attended_at

        # ----------------------------------------------------
        # SCREENING REMAINS REVIEWED
        # ----------------------------------------------------

        screening = (
            db.query(Screening)
            .filter(
                Screening.id
                == appointment.screening_id
            )
            .first()
        )

        if screening and user.role.upper() in {"DOCTOR", "HOSPITAL_ADMIN", "SUPER_ADMIN"}:
            _record_hospital_attendance(db, screening, user, appointment=appointment, attended_at=attended_at)
        elif user.role.upper() in {"DOCTOR", "HOSPITAL_ADMIN", "SUPER_ADMIN"}:
            _resolve_missed_appointment_notification(db, appointment.id, user, attended_at)

        db.commit()

        db.refresh(appointment)

        return {

            "message": (
                "Appointment marked as attended"
            ),

            "appointment_id": (
                appointment.id
            ),

            "patient_id": (
                appointment.patient_id
            ),

            "status": (
                appointment.status
            ),

            "screening_status": (
                screening.status
                if screening
                else None
            ),
            "hospital_attended_at": screening.hospital_attended_at if screening else None,
        }

    finally:

        db.close()


# ============================================================
# GET HEALTH CENTRE NOTIFICATIONS
# ============================================================

@app.get(
    "/health-centre/{health_centre_id}/notifications"
)
def get_health_centre_notifications(
    health_centre_id: int,
    authorization: str | None = Header(default=None),
):

    db = SessionLocal()

    try:

        current_user = _authenticated_user(authorization, db)
        if current_user.health_centre_id != health_centre_id or current_user.role.upper() not in {"HEALTH_CENTRE", "HEALTH CENTRE", "HEALTH_CENTRE_USER", "HEALTH_CENTRE_STAFF"}:
            raise HTTPException(status_code=403, detail="You cannot view notifications for this health centre")
        if not db.query(HealthCentre.id).filter_by(id=health_centre_id, is_active=True).first():
            raise HTTPException(status_code=403, detail="Health-centre account is inactive")

        health_centre = (
            db.query(HealthCentre)
            .filter(
                HealthCentre.id
                == health_centre_id
            )
            .first()
        )

        if not health_centre:

            raise HTTPException(
                status_code=404,
                detail="Health centre not found",
            )

        notifications = (
            db.query(Notification, Patient)
            .join(Patient, Notification.patient_id == Patient.id)
            .filter(
                Notification.health_centre_id == health_centre_id,
            )
            .order_by(
                Notification.created_at.desc()
            )
            .all()
        )

        result = []

        for notification, patient in notifications:
            appointment = (db.query(Appointment).filter_by(id=notification.appointment_id,
                health_centre_id=health_centre_id).first() if notification.appointment_id else None)
            referral = (db.query(Screening).filter_by(id=notification.referral_screening_id,
                health_centre_id=health_centre_id).first() if notification.referral_screening_id else None)
            hospital_id = notification.assigned_hospital_id or (referral.routed_hospital_id if referral else None)
            hospital = db.query(Hospital).filter_by(id=hospital_id).first() if hospital_id else None
            referral_deadline = None
            if referral and referral.submitted_at:
                submitted = referral.submitted_at
                submitted_utc = submitted.replace(tzinfo=timezone.utc) if submitted.tzinfo is None else submitted.astimezone(timezone.utc)
                referral_days = int(os.getenv("REFERRAL_ATTENDANCE_FOLLOW_UP_DAYS", "5"))
                referral_deadline = (submitted_utc.astimezone(clinic_timezone()) + timedelta(days=referral_days)).astimezone(timezone.utc)

            result.append(
                {
                    "id": notification.id,

                    "patient_id": (
                        notification.patient_id
                    ),

                    "patient_name": patient.name,

                    "patient_code": patient.patient_code,
                    "patient_phone": notification.patient_phone or patient.phone,
                    "appointment_time": notification.appointment_time,

                    "appointment_id": (
                        notification.appointment_id
                    ),
                    "report_id": appointment.screening_id if appointment else (referral.id if referral else None),
                    "referral_screening_id": notification.referral_screening_id,

                    "notification_type": (
                        notification.notification_type
                    ),

                    "message": (
                        notification.message
                    ),

                    "is_read": (
                        notification.is_read
                    ),

                    "created_at": (
                        notification.created_at
                    ),
                    "resolved_at": notification.resolved_at,
                    "status": "Resolved" if notification.resolved_at else "Follow-up required",
                    "assigned_hospital": hospital.name if hospital else None,
                    "doctor_name": appointment.doctor_name if appointment else None,
                    "appointment_datetime": appointment.appointment_datetime if appointment else None,
                    "appointment_status": appointment.status if appointment else None,
                    "missed_detected_at": appointment.missed_detected_at if appointment else None,
                    "referral_submitted_at": referral.submitted_at if referral else None,
                    "referral_deadline_at": referral_deadline,
                }
            )

        return {
            "total_notifications": len(result),
            "notifications": result,
        }

    finally:

        db.close()


@app.get("/health-centre/{health_centre_id}/screenings")
def health_centre_screenings(health_centre_id: int, authorization: str | None = Header(default=None)):
    db = SessionLocal()
    try:
        user = _authenticated_user(authorization, db)
        _require_health_centre_staff(user, health_centre_id, db)
        reports = (db.query(Screening).filter_by(health_centre_id=health_centre_id)
            .order_by(Screening.created_at.desc()).all())
        result = []
        for report in reports:
            appointments = db.query(Appointment).filter_by(screening_id=report.id,
                health_centre_id=health_centre_id).order_by(Appointment.appointment_datetime.desc()).all()
            next_appointment = next((a for a in appointments if a.status == "SCHEDULED"), appointments[0] if appointments else None)
            hospital = db.query(Hospital).filter_by(id=report.routed_hospital_id).first() if report.routed_hospital_id else None
            result.append({"screening_id": report.id, "patient_id": report.patient_id,
                "patient_name": report.patient.name if report.patient else None,
                "patient_code": report.patient.patient_code if report.patient else None,
                "patient_age": report.patient.age if report.patient else None,
                "patient_sex": report.patient.sex if report.patient else None,
                "patient_phone": report.patient.phone if report.patient else None,
                "originating_health_centre_id": report.health_centre_id,
                "screening_date": report.created_at, "prediction": report.prediction,
                "confidence": report.confidence,
                "probabilities": json.loads(report.probabilities or "{}"),
                "original_report_pdf_available": bool(resolve_private_file(report.original_report_pdf_path)),
                "original_pdf_url": f"/screening/{report.id}/original-pdf" if report.original_report_pdf_path else None,
                "original_image_url": f"/screening/{report.id}/original-image" if report.retinal_image_path else None,
                "gradcam_image_path": f"/screening/{report.id}/heatmap" if report.original_heatmap_path else None,
                "submitted_at": report.submitted_at, "submitted_to_hospital": report.submitted_to_hospital,
                "hospital_name": hospital.name if hospital else None,
                "review_status": report.review_status, "clinical_disposition": report.clinical_disposition,
                "clinical_outcome": report.clinical_outcome, "follow_up_required": report.follow_up_required,
                "clinical_review_notes": report.clinical_review_notes,
                "clinically_flagged": report.clinically_flagged,
                "clinical_reviewed_at": report.clinical_reviewed_at,
                "doctor_name": report.consulted_doctor,
                "doctor_notes": report.doctor_notes,
                "follow_up_priority": report.follow_up_priority,
                "disposition_updated_at": report.disposition_updated_at,
                "hospital_attended_at": report.hospital_attended_at,
                "referral_status": "REFERRED" if report.submitted_to_hospital == "YES" else "NOT_SUBMITTED",
                "appointment": format_appointment(next_appointment)})
        return {"screenings": result, "count": len(result)}
    finally:
        db.close()


# ============================================================
# MARK NOTIFICATION AS READ
# ============================================================

@app.patch(
    "/notifications/{notification_id}/read"
)
def mark_notification_read(
    notification_id: int,
    authorization: str | None = Header(default=None),
):

    db = SessionLocal()

    try:

        current_user = _authenticated_user(authorization, db)

        notification = (
            db.query(Notification)
            .filter(
                Notification.id
                == notification_id
            )
            .first()
        )

        if not notification:

            raise HTTPException(
                status_code=404,
                detail="Notification not found",
            )

        role = current_user.role.upper()
        if role in {"HEALTH_CENTRE", "HEALTH CENTRE", "HEALTH_CENTRE_USER", "HEALTH_CENTRE_STAFF"}:
            if current_user.health_centre_id != notification.health_centre_id:
                raise HTTPException(status_code=403, detail="You cannot update this notification")
        elif role in {"HOSPITAL_ADMIN", "DOCTOR"}:
            if current_user.hospital_id != notification.assigned_hospital_id:
                raise HTTPException(status_code=403, detail="You cannot update this notification")
        else:
            raise HTTPException(status_code=403, detail="You cannot update this notification")

        notification.is_read = True
        notification.acknowledged_at = datetime.utcnow()

        db.commit()

        db.refresh(notification)

        return {
            "message": "Notification marked as read",

            "notification_id": (
                notification.id
            ),

            "is_read": (
                notification.is_read
            ),
        }

    finally:

        db.close()


# Hospital network administration and routing API
def _require_super_admin(user):
    if user.role.upper() != "SUPER_ADMIN":
        raise HTTPException(status_code=403, detail="Super administrator access required")


def _require_hospital_user(user, db=None):
    if user.role.upper() not in {"HOSPITAL_ADMIN", "DOCTOR"} or not user.hospital_id:
        raise HTTPException(status_code=403, detail="Hospital access required")
    if db is not None and not db.query(Hospital.id).filter_by(id=user.hospital_id, is_active=True).first():
        raise HTTPException(status_code=403, detail="Hospital account is inactive")


def _hospital_dict(h):
    return {"id": h.id, "name": h.name, "code": h.code, "district": h.district, "state": h.state,
            "address": h.address, "contact_number": h.contact_number, "official_email": h.official_email,
            "is_active": h.is_active, "health_centre_count": len(h.health_centres),
            "pending_reports": sum(1 for s in h.health_centres for p in s.patients for r in p.screenings if r.routed_hospital_id == h.id and r.review_status == "PENDING"),
            "missed_follow_up": 0}


def _centre_dict(db, centre):
    return {"id": centre.id, "name": centre.name, "code": centre.code, "district": centre.district,
            "state": centre.state, "address": centre.address, "contact_number": centre.contact_number,
            "assigned_hospital_id": centre.assigned_hospital_id, "hospital_name": centre.hospital.name if centre.hospital else None,
            "is_active": centre.is_active, "patient_count": db.query(Patient).filter_by(health_centre_id=centre.id).count(),
            "report_count": db.query(Screening).filter_by(health_centre_id=centre.id).count(),
            "pending_reports": db.query(Screening).filter_by(health_centre_id=centre.id, review_status="PENDING").count(),
            "missed_follow_up": db.query(Notification).filter(Notification.health_centre_id == centre.id,
                Notification.notification_type.in_(["MISSED_APPOINTMENT", "REFERRAL_NON_ATTENDANCE"]),
                Notification.hospital_follow_up_at.is_(None), Notification.resolved_at.is_(None)).count()}


class HospitalPayload(BaseModel):
    name: str
    code: str
    district: str | None = None
    state: str | None = None
    address: str | None = None
    contact_number: str | None = None
    official_email: str | None = None
    is_active: bool = True


class HealthCentrePayload(BaseModel):
    name: str
    code: str
    district: str | None = None
    state: str | None = None
    address: str | None = None
    contact_number: str | None = None
    assigned_hospital_id: int | None = None
    is_active: bool = True


class ReviewPayload(BaseModel):
    notes: str | None = None
    flagged: bool = False
    doctor_name: str | None = None
    recommendations: str | None = None
    appointment_datetime: datetime | None = None
    appointment_type: str = "Hospital Consultation"
    appointment_notes: str | None = None
    follow_up_priority: str | None = None
    clinical_disposition: str | None = None
    clinical_outcome: str | None = None
    follow_up_required: bool | None = None


class HospitalAppointmentUpdate(BaseModel):
    appointment_datetime: datetime | None = None
    doctor_name: str | None = None
    notes: str | None = None
    status: str | None = None


class HospitalAppointmentCreate(BaseModel):
    appointment_datetime: datetime
    doctor_name: str
    appointment_type: str = "Hospital Consultation"
    notes: str | None = None


class FollowUpPayload(BaseModel):
    note: str


class ClinicalDispositionPayload(BaseModel):
    disposition: str
    note: str | None = None
    clinical_outcome: str | None = None
    follow_up_required: bool | None = None
    appointment_datetime: datetime | None = None
    doctor_name: str | None = None
    appointment_type: str = "Hospital Consultation"
    appointment_notes: str | None = None


def _validated_disposition(disposition, outcome, follow_up_required, monitoring_plan):
    value = (disposition or "").strip().upper()
    allowed = {"FOLLOW_UP_REQUIRED", "STABLE_MONITORING", "DISCHARGED_CARE_COMPLETED"}
    if value not in allowed:
        raise HTTPException(422, "Choose Follow-up Required, Stable — Monitoring, or Discharged / Care Completed")
    outcome_value = (outcome or "").strip().upper() or None
    outcomes = {"RECOVERED", "DISCHARGED_WITHOUT_DOCUMENTED_RECOVERY"}
    if value == "DISCHARGED_CARE_COMPLETED":
        if outcome_value not in outcomes:
            raise HTTPException(422, "Choose whether the patient recovered as documented or was discharged without documented recovery")
        return value, outcome_value, False
    if outcome_value is not None:
        raise HTTPException(422, "A clinical outcome is only used with Discharged / Care Completed")
    if value == "FOLLOW_UP_REQUIRED":
        return value, None, True
    if follow_up_required is not True:
        raise HTTPException(422, "Stable — Monitoring requires further monitoring or review to be selected")
    if not (monitoring_plan or "").strip():
        raise HTTPException(422, "Document the monitoring or review plan in Recommendations / next steps")
    return value, None, True


@app.patch("/hospital/reports/{screening_id}/disposition")
def set_clinical_disposition(screening_id: int, payload: ClinicalDispositionPayload, authorization: str | None = Header(default=None)):
    db = SessionLocal()
    try:
        user = _authenticated_user(authorization, db); _require_hospital_user(user, db)
        screening = db.query(Screening).filter_by(id=screening_id, routed_hospital_id=user.hospital_id, submitted_to_hospital="YES").first()
        if not screening:
            raise HTTPException(404, "Report not found in this hospital")
        if screening.review_status != "REVIEWED" or screening.clinical_reviewed_at is None:
            raise HTTPException(409, "Record a clinical review before updating the care disposition")
        plan = payload.note if payload.note is not None else screening.doctor_notes
        value, outcome, follow_up_required = _validated_disposition(
            payload.disposition, payload.clinical_outcome, payload.follow_up_required, plan)
        appointment = None
        if value in {"FOLLOW_UP_REQUIRED", "STABLE_MONITORING"}:
            if payload.appointment_datetime is None:
                raise HTTPException(422, "A future appointment date and time are required for this disposition")
            try:
                scheduled_when = clinic_local_datetime(payload.appointment_datetime)
            except ValueError as exc:
                raise HTTPException(400, str(exc))
            if scheduled_when <= datetime.now(clinic_timezone()).replace(tzinfo=None):
                raise HTTPException(422, "Consultation must be scheduled in the future")
            doctor_name = (payload.doctor_name or screening.consulted_doctor or user.name or "").strip()
            if not doctor_name:
                raise HTTPException(422, "Reviewing doctor's name is required")
            appointment = (db.query(Appointment).filter_by(screening_id=screening.id,
                hospital_id=user.hospital_id, status="SCHEDULED")
                .order_by(Appointment.appointment_datetime.asc()).first())
            if appointment:
                appointment.appointment_datetime = scheduled_when
                appointment.appointment_end_datetime = _appointment_end_utc(scheduled_when)
                appointment.doctor_name = doctor_name
                appointment.appointment_type = payload.appointment_type.strip() or "Hospital Consultation"
                appointment.notes = payload.appointment_notes or plan
                appointment.missed_detected_at = None
                appointment.updated_at = datetime.utcnow()
            else:
                appointment = Appointment(screening_id=screening.id, patient_id=screening.patient_id,
                    hospital_id=user.hospital_id, health_centre_id=screening.health_centre_id,
                    doctor_name=doctor_name, appointment_datetime=scheduled_when,
                    appointment_end_datetime=_appointment_end_utc(scheduled_when),
                    appointment_type=payload.appointment_type.strip() or "Hospital Consultation",
                    status="SCHEDULED", notes=payload.appointment_notes or plan)
                db.add(appointment)
            screening.consulted_doctor = doctor_name
        screening.clinical_disposition = value
        screening.clinical_outcome = outcome
        screening.follow_up_required = follow_up_required
        screening.disposition_recorded_by = user.id
        screening.disposition_updated_at = datetime.utcnow()
        if payload.note is not None:
            screening.doctor_notes = payload.note.strip() or None
        db.add(NetworkAudit(actor_user_id=user.id, health_centre_id=screening.health_centre_id,
            new_hospital_id=user.hospital_id, action="CLINICAL_DISPOSITION_UPDATED",
            details=f"screening_id={screening.id}; disposition={value}"))
        db.commit()
        if appointment:
            db.refresh(appointment)
        return {"screening_id": screening.id, "clinical_disposition": screening.clinical_disposition,
            "clinical_outcome": screening.clinical_outcome, "follow_up_required": screening.follow_up_required,
            "disposition_updated_at": screening.disposition_updated_at, "disposition_recorded_by": user.id,
            "appointment": format_appointment(appointment)}
    except HTTPException:
        db.rollback(); raise
    finally:
        db.close()


class OrganisationAccountPayload(BaseModel):
    username: str
    password: str
    name: str


class AccountStatusPayload(BaseModel):
    is_active: bool


class PasswordResetPayload(BaseModel):
    password: str


def _validate_account_credentials(username, password):
    import re
    username = username.strip()
    if not re.fullmatch(r"[A-Za-z0-9_.@+-]{3,64}", username):
        raise HTTPException(422, "Username must be 3–64 characters and use letters, numbers, or . _ @ + -")
    if len(password) < 12:
        raise HTTPException(422, "Password must contain at least 12 characters")
    if len(password) > 128:
        raise HTTPException(422, "Password must be at most 128 characters")
    return username


@app.post("/admin/accounts/{organisation_type}/{organisation_id}")
def create_organisation_account(organisation_type: str, organisation_id: int, payload: OrganisationAccountPayload, authorization: str | None = Header(default=None)):
    db = SessionLocal()
    try:
        _require_super_admin(_authenticated_user(authorization, db))
        username = _validate_account_credentials(payload.username, payload.password)
        if db.query(User).filter(User.username.ilike(username)).first():
            raise HTTPException(409, "Username already exists")
        if organisation_type == "hospital":
            organisation = db.query(Hospital).filter_by(id=organisation_id).first()
            role, filter_key = "HOSPITAL_ADMIN", "hospital_id"
        elif organisation_type in {"health-centre", "health_centre"}:
            organisation = db.query(HealthCentre).filter_by(id=organisation_id).first()
            role, filter_key = "HEALTH_CENTRE_USER", "health_centre_id"
        else:
            raise HTTPException(404, "Organisation type not found")
        if not organisation:
            raise HTTPException(404, "Organisation not found")
        account_roles = [role, "HEALTH_CENTRE", "HEALTH CENTRE", "HEALTH_CENTRE_STAFF"] if role == "HEALTH_CENTRE_USER" else [role]
        if db.query(User).filter(getattr(User, filter_key) == organisation_id, User.role.in_(account_roles)).first():
            raise HTTPException(409, "This organisation already has a login account")
        account = User(name=payload.name.strip() or organisation.name, username=username,
                       password_hash=hash_password(payload.password), role=role,
                       hospital_id=organisation_id if role == "HOSPITAL_ADMIN" else None,
                       health_centre_id=organisation_id if role == "HEALTH_CENTRE_USER" else None,
                       is_active=True)
        db.add(account)
        db.commit()
        return {"account": {"role": account.role, "is_active": account.is_active}}
    except HTTPException:
        db.rollback()
        raise
    finally:
        db.close()


@app.patch("/admin/accounts/{organisation_type}/{organisation_id}")
def set_organisation_account_status(organisation_type: str, organisation_id: int, payload: AccountStatusPayload, authorization: str | None = Header(default=None)):
    db = SessionLocal()
    try:
        _require_super_admin(_authenticated_user(authorization, db))
        if organisation_type == "hospital":
            account = db.query(User).filter_by(hospital_id=organisation_id, role="HOSPITAL_ADMIN").first()
        elif organisation_type in {"health-centre", "health_centre"}:
            account = db.query(User).filter(User.health_centre_id == organisation_id, User.role.in_(["HEALTH_CENTRE_USER", "HEALTH_CENTRE", "HEALTH CENTRE", "HEALTH_CENTRE_STAFF"])).first()
        else:
            raise HTTPException(404, "Organisation type not found")
        if not account:
            raise HTTPException(404, "Organisation account not found")
        account.is_active = payload.is_active
        db.commit()
        return {"account": {"role": account.role, "is_active": account.is_active}}
    except HTTPException:
        db.rollback()
        raise
    finally:
        db.close()


@app.post("/admin/accounts/{organisation_type}/{organisation_id}/reset-password")
def reset_organisation_password(organisation_type: str, organisation_id: int, payload: PasswordResetPayload, authorization: str | None = Header(default=None)):
    db = SessionLocal()
    try:
        _require_super_admin(_authenticated_user(authorization, db))
        _validate_account_credentials("valid_user", payload.password)
        if organisation_type == "hospital":
            account = db.query(User).filter_by(hospital_id=organisation_id, role="HOSPITAL_ADMIN").first()
        elif organisation_type in {"health-centre", "health_centre"}:
            account = db.query(User).filter(User.health_centre_id == organisation_id, User.role.in_(["HEALTH_CENTRE_USER", "HEALTH_CENTRE", "HEALTH CENTRE", "HEALTH_CENTRE_STAFF"])).first()
        else:
            raise HTTPException(404, "Organisation type not found")
        if not account:
            raise HTTPException(404, "Organisation account not found")
        account.password_hash = hash_password(payload.password)
        db.commit()
        return {"message": "Password reset successfully"}
    except HTTPException:
        db.rollback()
        raise
    finally:
        db.close()


@app.get("/admin/overview")
def admin_overview(authorization: str | None = Header(default=None)):
    db = SessionLocal()
    try:
        _require_super_admin(_authenticated_user(authorization, db))
        return {"hospitals": db.query(Hospital).count(), "health_centres": db.query(HealthCentre).count(),
                "patients": db.query(Patient).count(), "reports": db.query(Screening).count(),
                "pending_reviews": db.query(Screening).filter(Screening.routed_hospital_id.isnot(None), Screening.review_status == "PENDING").count(),
                "awaiting_assignment": db.query(Screening).filter(Screening.review_status == "AWAITING_ASSIGNMENT").count(),
                "missed_follow_up": db.query(Notification).filter(Notification.notification_type.in_(["MISSED_APPOINTMENT", "REFERRAL_NON_ATTENDANCE"]),
                    Notification.hospital_follow_up_at.is_(None), Notification.resolved_at.is_(None)).count()}
    finally: db.close()


@app.get("/admin/hospitals")
def admin_hospitals(authorization: str | None = Header(default=None)):
    db = SessionLocal()
    try:
        _require_super_admin(_authenticated_user(authorization, db))
        rows = db.query(Hospital).order_by(Hospital.name).all()
        result = []
        for h in rows:
            item = _hospital_dict(h)
            account = db.query(User).filter(User.hospital_id == h.id, User.role == "HOSPITAL_ADMIN").first()
            item["account_status"] = "not_created" if not account else ("active" if account.is_active else "disabled")
            centre_ids = [c.id for c in h.health_centres]
            item["pending_reports"] = db.query(Screening).filter(Screening.routed_hospital_id == h.id, Screening.review_status == "PENDING").count()
            item["missed_follow_up"] = db.query(Notification).filter(Notification.assigned_hospital_id == h.id,
                Notification.hospital_follow_up_at.is_(None), Notification.resolved_at.is_(None)).count()
            result.append(item)
        return {"hospitals": result}
    finally: db.close()


@app.post("/admin/hospitals")
def create_hospital(payload: HospitalPayload, authorization: str | None = Header(default=None)):
    db = SessionLocal()
    try:
        user = _authenticated_user(authorization, db); _require_super_admin(user)
        row = Hospital(**payload.model_dump())
        row.code = row.code.strip().upper()
        if db.query(Hospital).filter(Hospital.code == row.code).first(): raise HTTPException(409, "Hospital code already exists")
        db.add(row); db.commit(); db.refresh(row)
        return {"hospital": _hospital_dict(row)}
    except HTTPException: db.rollback(); raise
    finally: db.close()


@app.patch("/admin/hospitals/{hospital_id}")
def update_hospital(hospital_id: int, payload: HospitalPayload, authorization: str | None = Header(default=None)):
    db = SessionLocal()
    try:
        _require_super_admin(_authenticated_user(authorization, db))
        row = db.query(Hospital).filter_by(id=hospital_id).first()
        if not row: raise HTTPException(404, "Hospital not found")
        if row.is_active and not payload.is_active and db.query(HealthCentre).filter_by(assigned_hospital_id=hospital_id, is_active=True).count():
            raise HTTPException(409, "Reassign or deactivate this hospital's active health centres first")
        code = payload.code.strip().upper()
        if db.query(Hospital).filter(Hospital.code == code, Hospital.id != hospital_id).first(): raise HTTPException(409, "Hospital code already exists")
        for key, value in payload.model_dump().items(): setattr(row, key, code if key == "code" else value)
        db.commit(); return {"hospital": _hospital_dict(row)}
    except HTTPException: db.rollback(); raise
    finally: db.close()


@app.get("/admin/health-centres")
def admin_health_centres(hospital_id: int | None = None, district: str | None = None, unassigned: bool = False, authorization: str | None = Header(default=None)):
    db = SessionLocal()
    try:
        _require_super_admin(_authenticated_user(authorization, db))
        query = db.query(HealthCentre)
        if hospital_id is not None: query = query.filter(HealthCentre.assigned_hospital_id == hospital_id)
        if unassigned: query = query.filter(HealthCentre.assigned_hospital_id.is_(None))
        if district and district.strip():
            from sqlalchemy import func
            query = query.filter(func.lower(func.trim(HealthCentre.district)) == district.strip().lower())
        rows = query.order_by(HealthCentre.name).all()
        result = []
        for centre in rows:
            item = _centre_dict(db, centre)
            account = db.query(User).filter(User.health_centre_id == centre.id, User.role.in_(["HEALTH_CENTRE_USER", "HEALTH_CENTRE", "HEALTH CENTRE", "HEALTH_CENTRE_STAFF"])).first()
            item["account_status"] = "not_created" if not account else ("active" if account.is_active else "disabled")
            result.append(item)
        districts = sorted({(value or "").strip() for (value,) in db.query(HealthCentre.district).all() if value and value.strip()}, key=str.casefold)
        return {"health_centres": result, "districts": districts, "count": len(result)}
    finally: db.close()


@app.post("/admin/health-centres")
def create_health_centre(payload: HealthCentrePayload, authorization: str | None = Header(default=None)):
    db = SessionLocal()
    try:
        user = _authenticated_user(authorization, db); _require_super_admin(user)
        data = payload.model_dump(); data["code"] = data["code"].strip().upper()
        if db.query(HealthCentre).filter(HealthCentre.code == data["code"]).first(): raise HTTPException(409, "Health-centre code already exists")
        if data["assigned_hospital_id"] and not db.query(Hospital).filter_by(id=data["assigned_hospital_id"], is_active=True).first(): raise HTTPException(400, "Choose an active hospital")
        row = HealthCentre(**data); row.location = ", ".join(x for x in [row.district, row.state] if x)
        db.add(row); db.flush()
        db.add(NetworkAudit(actor_user_id=user.id, health_centre_id=row.id, new_hospital_id=row.assigned_hospital_id, action="HEALTH_CENTRE_CREATED"))
        db.commit(); db.refresh(row); return {"health_centre": _centre_dict(db, row)}
    except HTTPException: db.rollback(); raise
    finally: db.close()


@app.patch("/admin/health-centres/{centre_id}")
def update_health_centre(centre_id: int, payload: HealthCentrePayload, authorization: str | None = Header(default=None)):
    db = SessionLocal()
    try:
        user = _authenticated_user(authorization, db); _require_super_admin(user)
        row = db.query(HealthCentre).filter_by(id=centre_id).first()
        if not row: raise HTTPException(404, "Health centre not found")
        data = payload.model_dump(); data["code"] = data["code"].strip().upper()
        if db.query(HealthCentre).filter(HealthCentre.code == data["code"], HealthCentre.id != centre_id).first(): raise HTTPException(409, "Health-centre code already exists")
        target = data["assigned_hospital_id"]
        if target and not db.query(Hospital).filter_by(id=target, is_active=True).first(): raise HTTPException(400, "Choose an active hospital")
        old = row.assigned_hospital_id
        for key, value in data.items(): setattr(row, key, value)
        row.location = ", ".join(x for x in [row.district, row.state] if x)
        if old != target:
            db.add(NetworkAudit(actor_user_id=user.id, health_centre_id=row.id, old_hospital_id=old, new_hospital_id=target, action="HEALTH_CENTRE_REASSIGNED"))
            if old is None and target is not None:
                waiting_reports = db.query(Screening).filter_by(health_centre_id=row.id, routed_hospital_id=None, review_status="AWAITING_ASSIGNMENT").all()
                for report in waiting_reports:
                    report.routed_hospital_id = target
                    report.review_status = "PENDING"
                    report.routed_at = datetime.utcnow()
        db.commit(); db.refresh(row); return {"health_centre": _centre_dict(db, row)}
    except HTTPException: db.rollback(); raise
    finally: db.close()


@app.get("/hospital/dashboard")
def hospital_dashboard(authorization: str | None = Header(default=None)):
    db = SessionLocal()
    try:
        user = _authenticated_user(authorization, db); _require_hospital_user(user, db)
        hospital = db.query(Hospital).filter_by(id=user.hospital_id, is_active=True).first()
        if not hospital: raise HTTPException(403, "Hospital account is inactive")
        centres = db.query(HealthCentre).filter_by(assigned_hospital_id=hospital.id).all()
        reports = db.query(Screening).filter_by(routed_hospital_id=hospital.id, submitted_to_hospital="YES").all()
        notes = (db.query(Notification).filter(Notification.assigned_hospital_id == hospital.id,
            Notification.notification_type.in_(["MISSED_APPOINTMENT", "REFERRAL_NON_ATTENDANCE"]))
            .order_by(Notification.created_at.desc()).all())
        appointments = (db.query(Appointment).filter(Appointment.hospital_id == hospital.id,
            Appointment.status.in_(["SCHEDULED", "MISSED", "ATTENDED", "CANCELLED"]))
            .order_by(Appointment.appointment_datetime.desc()).all())
        next_appointments = {}
        clinic_now = datetime.now(clinic_timezone()).replace(tzinfo=None)
        for appt in appointments:
            if appt.screening_id and appt.screening_id not in next_appointments:
                next_appointments[appt.screening_id] = appt
        for appt in sorted(appointments, key=lambda item: item.appointment_datetime):
            current = next_appointments.get(appt.screening_id) if appt.screening_id else None
            if (appt.screening_id and appt.status == "SCHEDULED" and appt.appointment_datetime > clinic_now
                    and (current is None or current.status != "SCHEDULED" or appt.appointment_datetime < current.appointment_datetime)):
                next_appointments[appt.screening_id] = appt
        return {"hospital": _hospital_dict(hospital), "health_centres": [_centre_dict(db, c) for c in centres],
                "reports": [{"id": r.id, "patient_id": r.patient_id, "patient_code": r.patient.patient_code, "patient_name": r.patient.name,
                    "patient_age": r.patient.age, "patient_sex": r.patient.sex, "patient_phone": r.patient.phone,
                    "health_centre_id": r.health_centre_id, "health_centre": r.health_centre.name if r.health_centre else None,
                    "screening_date": r.created_at, "prediction": r.prediction, "confidence": r.confidence,
                    "probabilities": json.loads(r.probabilities or "{}"),
                    "gradcam_image_path": f"/screening/{r.id}/heatmap" if r.original_heatmap_path else None,
                    "screening_status": r.status,
                    "submitted_at": r.submitted_at, "hospital_attended_at": r.hospital_attended_at,
                    "original_pdf_url": f"/screening/{r.id}/original-pdf" if r.original_report_pdf_path else None,
                    "original_pdf_available": bool(resolve_private_file(r.original_report_pdf_path)),
                    "original_image_url": f"/screening/{r.id}/original-image" if r.retinal_image_path else None,
                    "submitted_to_hospital": r.submitted_to_hospital, "doctor_name": r.consulted_doctor,
                    "recommendations": r.doctor_notes, "clinical_review_doctor": r.consulted_doctor,
                    "review_status": r.review_status, "clinical_review_notes": r.clinical_review_notes,
                    "clinical_reviewed_at": r.clinical_reviewed_at,
                    "clinical_reviewer_id": r.clinical_reviewer_id,
                    "follow_up_priority": r.follow_up_priority,
                    "clinical_disposition": r.clinical_disposition,
                    "clinical_outcome": r.clinical_outcome,
                    "follow_up_required": r.follow_up_required,
                    "disposition_recorded_by": r.disposition_recorded_by,
                    "disposition_updated_at": r.disposition_updated_at,
                    "care_category": _hospital_care_category(r),
                    "clinically_flagged": r.clinically_flagged, "created_at": r.created_at,
                    "appointment": format_appointment(next_appointments.get(r.id))} for r in reports],
                "appointments": [{**format_appointment(a), "patient_id": a.patient_id,
                    "patient_name": a.patient.name if a.patient else None,
                    "patient_code": a.patient.patient_code if a.patient else None,
                    "health_centre_id": a.health_centre_id,
                    "health_centre": a.health_centre.name if a.health_centre else None,
                    "screening_id": a.screening_id} for a in appointments],
                "notifications": [{"id": n.id, "patient_id": n.patient_id, "patient_name": n.patient.name,
                    "patient_code": n.patient.patient_code, "appointment_id": n.appointment_id,
                    "referral_screening_id": n.referral_screening_id, "notification_type": n.notification_type,
                    "health_centre_id": n.health_centre_id, "health_centre": n.health_centre.name if n.health_centre else None,
                    "message": n.message, "created_at": n.created_at, "follow_up": n.hospital_follow_up,
                    "follow_up_at": n.hospital_follow_up_at, "resolved_at": n.resolved_at} for n in notes],
                "stats": {"health_centres": len(centres), "patients": db.query(Patient).filter(Patient.health_centre_id.in_([c.id for c in centres])).count() if centres else 0,
                    "reports": len(reports), "pending_reviews": sum(r.review_status in {"PENDING", "AWAITING_ASSIGNMENT"} for r in reports),
                    "urgent": sum(r.clinically_flagged or "proliferative" in (r.prediction or "").lower() or "severe" in (r.prediction or "").lower() for r in reports),
                    "missed_follow_up": sum(n.hospital_follow_up_at is None and n.resolved_at is None for n in notes)}}
    finally: db.close()


def _record_hospital_attendance(db, screening, user, appointment=None, attended_at=None):
    attended_at = attended_at or datetime.utcnow()
    if screening.hospital_attended_at is None:
        screening.hospital_attended_at = attended_at
        screening.hospital_attended_by = user.id
    if appointment:
        appointment.status = "ATTENDED"
        appointment.updated_at = attended_at
        _resolve_missed_appointment_notification(db, appointment.id, user, attended_at)
    referral_notifications = db.query(Notification).filter_by(referral_screening_id=screening.id,
        notification_type="REFERRAL_NON_ATTENDANCE").all()
    for notification in referral_notifications:
        if notification.resolved_at is None:
            notification.resolved_at = attended_at
            notification.resolved_by_user_id = user.id


def _resolve_missed_appointment_notification(db, appointment_id, user, attended_at):
    notifications = db.query(Notification).filter_by(appointment_id=appointment_id,
        notification_type="MISSED_APPOINTMENT").all()
    for notification in notifications:
        if notification.resolved_at is None:
            notification.resolved_at = attended_at
            notification.resolved_by_user_id = user.id


def _hospital_care_category(screening):
    disposition = (screening.clinical_disposition or "").upper()
    if disposition == "DISCHARGED_CARE_COMPLETED":
        return "RECOVERED_DISCHARGED"
    if not screening.clinical_reviewed_at and screening.review_status != "REVIEWED":
        return "NEWLY_ASSIGNED"
    if disposition == "FOLLOW_UP_REQUIRED":
        return "FOLLOW_UP_REQUIRED"
    if disposition == "STABLE_MONITORING" and screening.follow_up_required is True:
        return "FOLLOW_UP_REQUIRED"
    if not screening.hospital_attended_at:
        return "AWAITING_CONSULTATION"
    if disposition == "STABLE_MONITORING":
        return "DISPOSITION_REVIEW"
    if not disposition:
        return "DISPOSITION_REVIEW"
    # Reviewed active cases stay in follow-up until a clinician explicitly documents
    # recovery or discharge. Missing disposition is never interpreted as cured.
    return "FOLLOW_UP_REQUIRED"


class HospitalAttendancePayload(BaseModel):
    appointment_id: int | None = None


@app.post("/hospital/reports/{screening_id}/attendance")
def record_hospital_attendance(screening_id: int, payload: HospitalAttendancePayload, authorization: str | None = Header(default=None)):
    db = SessionLocal()
    try:
        user = _authenticated_user(authorization, db); _require_hospital_user(user, db)
        screening = db.query(Screening).filter_by(id=screening_id, routed_hospital_id=user.hospital_id, submitted_to_hospital="YES").first()
        if not screening:
            raise HTTPException(404, "Report not found in this hospital")
        appointment = None
        if payload.appointment_id is not None:
            appointment = db.query(Appointment).filter_by(id=payload.appointment_id,
                screening_id=screening.id, hospital_id=user.hospital_id).first()
            if not appointment:
                raise HTTPException(404, "Appointment not found for this report")
            if appointment.status not in {"SCHEDULED", "MISSED", "ATTENDED"}:
                raise HTTPException(409, "Cancelled appointments cannot be checked in")
        attended_at = screening.hospital_attended_at or datetime.utcnow()
        _record_hospital_attendance(db, screening, user, appointment=appointment, attended_at=attended_at)
        db.commit()
        return {"message": "Hospital attendance recorded", "screening_id": screening.id,
            "appointment_id": appointment.id if appointment else None, "hospital_attended_at": screening.hospital_attended_at}
    except HTTPException:
        db.rollback()
        raise
    finally:
        db.close()


@app.post("/hospital/reports/{screening_id}/appointments")
def create_hospital_appointment(screening_id: int, payload: HospitalAppointmentCreate, authorization: str | None = Header(default=None)):
    db = SessionLocal()
    try:
        user = _authenticated_user(authorization, db); _require_hospital_user(user, db)
        screening = db.query(Screening).filter_by(id=screening_id, routed_hospital_id=user.hospital_id, submitted_to_hospital="YES").first()
        if not screening:
            raise HTTPException(404, "Report not found in this hospital inbox")
        doctor_name = payload.doctor_name.strip()
        if not doctor_name:
            raise HTTPException(422, "Reviewing doctor's name is required")
        try:
            scheduled_when = clinic_local_datetime(payload.appointment_datetime)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        if scheduled_when <= datetime.now(clinic_timezone()).replace(tzinfo=None):
            raise HTTPException(422, "Consultation must be scheduled in the future")
        centre = db.query(HealthCentre).filter_by(id=screening.health_centre_id).first()
        if not centre or centre.assigned_hospital_id != user.hospital_id:
            raise HTTPException(409, "This health centre is no longer assigned to your hospital")
        duplicate = db.query(Appointment).filter_by(screening_id=screening.id, hospital_id=user.hospital_id,
            appointment_datetime=scheduled_when, status="SCHEDULED").first()
        if duplicate:
            return {"message": "This consultation is already scheduled", "appointment": format_appointment(duplicate), "duplicate": True}
        appointment = Appointment(screening_id=screening.id, patient_id=screening.patient_id,
            hospital_id=user.hospital_id, health_centre_id=screening.health_centre_id,
            doctor_name=doctor_name, appointment_datetime=scheduled_when,
            appointment_end_datetime=_appointment_end_utc(scheduled_when),
            appointment_type=payload.appointment_type.strip() or "Hospital Consultation",
            notes=payload.notes, status="SCHEDULED")
        db.add(appointment); db.commit(); db.refresh(appointment)
        return {"message": "Consultation scheduled", "appointment": format_appointment(appointment), "duplicate": False}
    except HTTPException:
        db.rollback()
        raise
    finally:
        db.close()


@app.post("/hospital/reports/{screening_id}/review")
def review_routed_report(screening_id: int, payload: ReviewPayload, authorization: str | None = Header(default=None)):
    db = SessionLocal()
    try:
        user = _authenticated_user(authorization, db); _require_hospital_user(user, db)
        row = db.query(Screening).filter_by(id=screening_id, routed_hospital_id=user.hospital_id, submitted_to_hospital="YES").first()
        if not row: raise HTTPException(404, "Report not found in this hospital inbox")
        disposition_value = (payload.clinical_disposition or row.clinical_disposition or "").strip().upper()
        requires_appointment = disposition_value in {"FOLLOW_UP_REQUIRED", "STABLE_MONITORING"}
        if payload.clinical_disposition is not None:
            if not (payload.notes or "").strip():
                raise HTTPException(422, "Document the clinical assessment before completing this review")
            if not (payload.doctor_name or "").strip():
                raise HTTPException(422, "Reviewing doctor's name is required")
            if requires_appointment and payload.appointment_datetime is None:
                raise HTTPException(422, "A future appointment date and time are required for this disposition")
        row.clinical_review_notes = payload.notes; row.clinically_flagged = payload.flagged
        row.clinical_reviewer_id = user.id; row.review_status = "REVIEWED"
        row.clinical_reviewed_at = datetime.utcnow()
        if payload.recommendations is not None:
            row.doctor_notes = payload.recommendations.strip() or None
        if payload.follow_up_priority is not None:
            priority = payload.follow_up_priority.strip().upper()
            if priority not in {"ROUTINE", "PRIORITY", "URGENT"}:
                raise HTTPException(422, "Follow-up priority must be ROUTINE, PRIORITY, or URGENT")
            row.follow_up_priority = priority
        if payload.clinical_disposition is not None:
            disposition, outcome, follow_up_required = _validated_disposition(
                payload.clinical_disposition, payload.clinical_outcome,
                payload.follow_up_required, row.doctor_notes)
            row.clinical_disposition = disposition
            row.clinical_outcome = outcome
            row.follow_up_required = follow_up_required
            row.disposition_recorded_by = user.id
            row.disposition_updated_at = datetime.utcnow()
        elif payload.clinical_outcome is not None or payload.follow_up_required is not None:
            raise HTTPException(422, "Clinical outcome and follow-up requirement must be saved with a clinical disposition")
        if payload.doctor_name is not None:
            doctor_name = payload.doctor_name.strip()
            if not doctor_name:
                raise HTTPException(422, "Reviewing doctor's name is required")
            row.consulted_doctor = doctor_name
        appointment = None
        if payload.appointment_datetime is not None:
            try:
                scheduled_when = clinic_local_datetime(payload.appointment_datetime)
            except ValueError as exc:
                raise HTTPException(400, str(exc))
            if scheduled_when <= datetime.now(clinic_timezone()).replace(tzinfo=None):
                raise HTTPException(422, "Consultation must be scheduled in the future")
            centre = db.query(HealthCentre).filter_by(id=row.health_centre_id).first()
            if not centre or centre.assigned_hospital_id != user.hospital_id:
                raise HTTPException(409, "This health centre is no longer assigned to your hospital")
            appointment = (db.query(Appointment).filter_by(screening_id=row.id, hospital_id=user.hospital_id, status="SCHEDULED")
                           .order_by(Appointment.appointment_datetime.asc()).first())
            duplicate_query = db.query(Appointment).filter_by(screening_id=row.id, hospital_id=user.hospital_id,
                appointment_datetime=scheduled_when, status="SCHEDULED")
            if appointment:
                duplicate_query = duplicate_query.filter(Appointment.id != appointment.id)
            if duplicate_query.first():
                raise HTTPException(409, "Another consultation for this report is already scheduled at that time")
            doctor_name = (payload.doctor_name or row.consulted_doctor or user.name).strip()
            appointment_notes = payload.appointment_notes
            if requires_appointment and not doctor_name:
                raise HTTPException(422, "Reviewing doctor's name is required to schedule this appointment")
            if appointment:
                appointment.appointment_datetime = scheduled_when
                appointment.appointment_end_datetime = _appointment_end_utc(scheduled_when)
                appointment.doctor_name = doctor_name
                appointment.appointment_type = payload.appointment_type.strip() or "Hospital Consultation"
                appointment.notes = appointment_notes
                appointment.updated_at = datetime.utcnow()
                appointment.missed_detected_at = None
            else:
                appointment = Appointment(screening_id=row.id, patient_id=row.patient_id,
                    hospital_id=user.hospital_id, health_centre_id=row.health_centre_id,
                    doctor_name=doctor_name, appointment_datetime=scheduled_when,
                    appointment_end_datetime=_appointment_end_utc(scheduled_when),
                    appointment_type=payload.appointment_type.strip() or "Hospital Consultation",
                    status="SCHEDULED", notes=appointment_notes)
                db.add(appointment)
        db.add(NetworkAudit(actor_user_id=user.id, health_centre_id=row.health_centre_id, new_hospital_id=user.hospital_id, action="CLINICAL_REVIEW", details=f"screening_id={row.id}; flagged={payload.flagged}"))
        db.commit()
        if appointment:
            db.refresh(appointment)
        return {"message": "Clinical review saved", "review_status": row.review_status,
                "ai_prediction": row.prediction, "appointment": format_appointment(appointment)}
    except HTTPException: db.rollback(); raise
    finally: db.close()


@app.patch("/hospital/appointments/{appointment_id}")
def update_hospital_appointment(appointment_id: int, payload: HospitalAppointmentUpdate, authorization: str | None = Header(default=None)):
    db = SessionLocal()
    try:
        user = _authenticated_user(authorization, db); _require_hospital_user(user, db)
        appointment = db.query(Appointment).filter_by(id=appointment_id, hospital_id=user.hospital_id).first()
        if not appointment:
            raise HTTPException(404, "Appointment not found in this hospital")
        if payload.status is not None and payload.appointment_datetime is not None:
            raise HTTPException(422, "Update appointment status and schedule time in separate requests")
        if appointment.status == "ATTENDED":
            raise HTTPException(409, "Completed appointments cannot be changed")
        response_appointment = appointment
        if payload.status is not None:
            status = payload.status.upper()
            if status not in {"ATTENDED", "CANCELLED"}:
                raise HTTPException(400, "Status must be ATTENDED or CANCELLED")
            if appointment.status not in {"SCHEDULED", "MISSED", "CANCELLED"}:
                raise HTTPException(409, "This appointment can no longer be changed")
            appointment.status = status
            if status == "ATTENDED" and appointment.screening_id:
                screening = db.query(Screening).filter_by(id=appointment.screening_id, routed_hospital_id=user.hospital_id).first()
                if screening:
                    _record_hospital_attendance(db, screening, user, appointment=appointment, attended_at=datetime.utcnow())
            elif status == "ATTENDED":
                _resolve_missed_appointment_notification(db, appointment.id, user, datetime.utcnow())
        rescheduled_missed = False
        if payload.appointment_datetime is not None:
            try:
                scheduled_when = clinic_local_datetime(payload.appointment_datetime)
            except ValueError as exc:
                raise HTTPException(400, str(exc))
            if scheduled_when <= datetime.now(clinic_timezone()).replace(tzinfo=None):
                raise HTTPException(422, "Consultation must be scheduled in the future")
            if appointment.status == "MISSED":
                # Keep the missed consultation and its audit notification; rescheduling
                # creates a distinct event with its own attendance/missed lifecycle.
                replacement_doctor = payload.doctor_name.strip() if payload.doctor_name is not None else appointment.doctor_name
                if not replacement_doctor:
                    raise HTTPException(422, "Reviewing doctor's name is required")
                replacement = (db.query(Appointment).filter_by(screening_id=appointment.screening_id,
                    hospital_id=appointment.hospital_id, status="SCHEDULED")
                    .order_by(Appointment.appointment_datetime.asc()).first())
                if replacement:
                    replacement.appointment_datetime = scheduled_when
                    replacement.appointment_end_datetime = _appointment_end_utc(scheduled_when)
                    replacement.doctor_name = replacement_doctor
                    if payload.notes is not None:
                        replacement.notes = payload.notes
                    replacement.updated_at = datetime.utcnow()
                else:
                    replacement = Appointment(screening_id=appointment.screening_id, patient_id=appointment.patient_id,
                        hospital_id=appointment.hospital_id, health_centre_id=appointment.health_centre_id,
                        appointment_datetime=scheduled_when, appointment_end_datetime=_appointment_end_utc(scheduled_when),
                        doctor_name=replacement_doctor,
                        appointment_type=appointment.appointment_type, notes=payload.notes if payload.notes is not None else appointment.notes,
                        status="SCHEDULED")
                    db.add(replacement)
                appointment.updated_at = datetime.utcnow()
                response_appointment = replacement
                rescheduled_missed = True
            else:
                appointment.appointment_datetime = scheduled_when
                appointment.appointment_end_datetime = _appointment_end_utc(scheduled_when)
                appointment.status = "SCHEDULED"
                appointment.missed_detected_at = None
        if payload.doctor_name is not None and not rescheduled_missed:
            doctor_name = payload.doctor_name.strip()
            if not doctor_name:
                raise HTTPException(422, "Reviewing doctor's name is required")
            appointment.doctor_name = doctor_name
        if payload.notes is not None and not rescheduled_missed:
            appointment.notes = payload.notes
        appointment.updated_at = datetime.utcnow()
        db.commit(); db.refresh(response_appointment)
        return {"appointment": format_appointment(response_appointment)}
    except HTTPException:
        db.rollback()
        raise
    finally:
        db.close()


@app.post("/hospital/notifications/{notification_id}/follow-up")
def hospital_follow_up(notification_id: int, payload: FollowUpPayload, authorization: str | None = Header(default=None)):
    db = SessionLocal()
    try:
        user = _authenticated_user(authorization, db); _require_hospital_user(user, db)
        row = db.query(Notification).filter(Notification.id == notification_id,
            Notification.assigned_hospital_id == user.hospital_id,
            Notification.notification_type.in_(["MISSED_APPOINTMENT", "REFERRAL_NON_ATTENDANCE"])).first()
        if not row: raise HTTPException(404, "Notification not found in this hospital")
        row.hospital_follow_up = payload.note; row.hospital_follow_up_by = user.id; row.hospital_follow_up_at = datetime.utcnow()
        db.commit(); return {"message": "Follow-up recorded", "notification_id": row.id}
    except HTTPException: db.rollback(); raise
    finally: db.close()
