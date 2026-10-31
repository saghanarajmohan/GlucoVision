"""Local, database-backed appointment processing. No external calendar dependency."""
import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import update

from backend.database import SessionLocal
from backend.models import Appointment, Notification, Screening, HealthCentre, Hospital, Patient

logger = logging.getLogger(__name__)
_stop = threading.Event()
_started = False
_start_lock = threading.Lock()
_thread = None


def _utcnow():
    return datetime.now(timezone.utc)


def clinic_timezone():
    return ZoneInfo(os.getenv("APP_TIMEZONE", "Asia/Kolkata"))


def clinic_local_datetime(value):
    """Convert an API date/time to clinic wall time and reject invalid DST times."""
    zone = clinic_timezone()
    if value.tzinfo is not None:
        value = value.astimezone(zone).replace(tzinfo=None)
    candidates = [value.replace(tzinfo=zone, fold=fold) for fold in (0, 1)]
    valid = [candidate for candidate in candidates if candidate.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) == value]
    offsets = {candidate.utcoffset() for candidate in valid}
    if not valid:
        raise ValueError("Appointment time does not exist in the configured time zone because of a daylight-saving transition")
    if len(offsets) > 1:
        raise ValueError("Appointment time is ambiguous in the configured time zone because of a daylight-saving transition")
    return value


def process_missed_appointments(now=None, grace_minutes=None, session_factory=None):
    """Atomically mark due unattended appointments and insert one HC notification."""
    now = now or _utcnow()
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    grace = int(grace_minutes if grace_minutes is not None else os.getenv("APPOINTMENT_GRACE_MINUTES", "15"))
    if grace < 0:
        raise ValueError("APPOINTMENT_GRACE_MINUTES must be zero or greater")
    db = (session_factory or SessionLocal)()
    changed = 0
    try:
        due = db.query(Appointment).filter(Appointment.status == "SCHEDULED").all()
        for appt in due:
            # Appointment datetimes are stored as clinic wall time for compatibility with
            # existing records; attach the configured IANA zone before comparing instants.
            scheduled_start = appt.appointment_datetime.replace(tzinfo=clinic_timezone()).astimezone(timezone.utc)
            local_appointment_date = scheduled_start.astimezone(clinic_timezone()).date()
            end_of_appointment_day = datetime.combine(
                local_appointment_date + timedelta(days=1),
                datetime.min.time(),
                tzinfo=clinic_timezone(),
            ).astimezone(timezone.utc)
            if now < end_of_appointment_day + timedelta(minutes=grace):
                continue
            patient = appt.patient
            if not patient or patient.health_centre_id != appt.health_centre_id:
                logger.warning("Skipping appointment %s because its patient and health-centre assignment do not match", appt.id)
                continue
            if appt.screening_id:
                screening = db.query(Screening).filter(Screening.id == appt.screening_id).first()
                if screening and screening.status.upper() in {"ATTENDED", "COMPLETED"}:
                    continue
            result = db.execute(
                update(Appointment)
                .where(Appointment.id == appt.id, Appointment.status == "SCHEDULED")
                .values(status="MISSED", missed_detected_at=now.astimezone(timezone.utc).replace(tzinfo=None), updated_at=now.astimezone(timezone.utc).replace(tzinfo=None))
            )
            if result.rowcount != 1:
                continue
            local_time = scheduled_start.astimezone(clinic_timezone()).strftime("%d %b %Y, %I:%M %p %Z")
            hospital = db.query(Hospital).filter_by(id=appt.hospital_id).first()
            message = (f"{patient.name} (Patient ID {patient.patient_code}, Report #{appt.screening_id or '—'}) did not attend the "
                       f"consultation scheduled for {local_time} at {hospital.name if hospital else 'the hospital'} with "
                       f"{appt.doctor_name}. Attendance was not recorded. Please contact the patient"
                       f"{f' at {patient.phone}' if patient.phone else ''} and arrange follow-up.")
            exists = db.query(Notification.id).filter(
                Notification.appointment_id == appt.id,
                Notification.notification_type == "MISSED_APPOINTMENT",
            ).first()
            if not exists:
                db.add(Notification(
                    health_centre_id=appt.health_centre_id,
                    patient_id=appt.patient_id,
                    appointment_id=appt.id,
                    assigned_hospital_id=appt.hospital_id,
                    notification_type="MISSED_APPOINTMENT",
                    message=message,
                    patient_phone=patient.phone,
                    appointment_time=local_time,
                    is_read=False,
                ))
            changed += 1
        db.commit()
        return changed
    except Exception:
        db.rollback()
        logger.exception("Appointment missed-status processing failed")
        raise
    finally:
        db.close()


def process_unattended_referrals(now=None, follow_up_days=None, session_factory=None):
    """Create one alert per submitted report after five clinic-calendar days without attendance."""
    now = now or _utcnow()
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    days = int(follow_up_days if follow_up_days is not None else os.getenv("REFERRAL_ATTENDANCE_FOLLOW_UP_DAYS", "5"))
    if days < 1:
        raise ValueError("REFERRAL_ATTENDANCE_FOLLOW_UP_DAYS must be at least one calendar day")
    db = (session_factory or SessionLocal)()
    created = 0
    try:
        referrals = db.query(Screening).filter(Screening.submitted_at.isnot(None),
            Screening.routed_hospital_id.isnot(None)).all()
        for report in referrals:
            submitted = report.submitted_at
            submitted_utc = submitted.replace(tzinfo=timezone.utc) if submitted.tzinfo is None else submitted.astimezone(timezone.utc)
            deadline = (submitted_utc.astimezone(clinic_timezone()) + timedelta(days=days)).astimezone(timezone.utc)
            if now.astimezone(timezone.utc) < deadline:
                continue

            attendance_at = report.hospital_attended_at
            if attendance_at is not None:
                attendance_utc = attendance_at.replace(tzinfo=timezone.utc) if attendance_at.tzinfo is None else attendance_at.astimezone(timezone.utc)
                if attendance_utc <= deadline:
                    continue
            else:
                attended_appointment = (db.query(Appointment).filter(Appointment.screening_id == report.id,
                    Appointment.hospital_id == report.routed_hospital_id, Appointment.status == "ATTENDED")
                    .order_by(Appointment.updated_at.asc()).first())
                if attended_appointment and attended_appointment.updated_at:
                    inferred_attendance = attended_appointment.updated_at.replace(tzinfo=timezone.utc) if attended_appointment.updated_at.tzinfo is None else attended_appointment.updated_at.astimezone(timezone.utc)
                    if inferred_attendance <= deadline:
                        report.hospital_attended_at = inferred_attendance.replace(tzinfo=None)
                        continue
                    attendance_at = inferred_attendance.replace(tzinfo=None)

            notification = db.query(Notification).filter_by(referral_screening_id=report.id,
                notification_type="REFERRAL_NON_ATTENDANCE").first()
            if not notification:
                patient = db.query(Patient).filter_by(id=report.patient_id).first()
                centre = db.query(HealthCentre).filter_by(id=report.health_centre_id).first()
                hospital = db.query(Hospital).filter_by(id=report.routed_hospital_id).first()
                if not patient or not centre:
                    continue
                deadline_local = deadline.astimezone(clinic_timezone()).strftime("%d %b %Y, %I:%M %p %Z")
                message = (f"{patient.name} (Patient ID {patient.patient_code}, Report #{report.id}) has no hospital attendance "
                    f"recorded within five calendar days of referral to {hospital.name if hospital else 'the hospital'} "
                    f"from {centre.name}. Deadline: {deadline_local}. Please contact the patient and follow up.")
                notification = Notification(health_centre_id=report.health_centre_id, patient_id=report.patient_id,
                    referral_screening_id=report.id, assigned_hospital_id=report.routed_hospital_id,
                    notification_type="REFERRAL_NON_ATTENDANCE", message=message, is_read=False,
                    created_at=now.astimezone(timezone.utc).replace(tzinfo=None))
                try:
                    with db.begin_nested():
                        db.add(notification)
                        db.flush()
                    created += 1
                except Exception:
                    # A parallel worker may have inserted the same referral alert.
                    existing = db.query(Notification.id).filter_by(referral_screening_id=report.id,
                        notification_type="REFERRAL_NON_ATTENDANCE").first()
                    if not existing:
                        raise
                    notification = db.query(Notification).filter_by(referral_screening_id=report.id,
                        notification_type="REFERRAL_NON_ATTENDANCE").first()
            if attendance_at is not None and notification.resolved_at is None:
                resolved = attendance_at.replace(tzinfo=timezone.utc) if attendance_at.tzinfo is None else attendance_at.astimezone(timezone.utc)
                notification.resolved_at = resolved.replace(tzinfo=None)
                notification.resolved_by_user_id = report.hospital_attended_by
        db.commit()
        return created
    except Exception:
        db.rollback()
        logger.exception("Referral non-attendance processing failed")
        raise
    finally:
        db.close()


def _run():
    interval = max(15, int(os.getenv("APPOINTMENT_CHECK_INTERVAL_SECONDS", "60")))
    while not _stop.is_set():
        try:
            process_missed_appointments()
        except Exception:
            logger.exception("Appointment scheduler iteration failed; will retry")
        try:
            process_unattended_referrals()
        except Exception:
            logger.exception("Referral non-attendance scheduler iteration failed; will retry")
        _stop.wait(interval)


def start_scheduler():
    global _started, _thread
    with _start_lock:
        if _thread is not None and _thread.is_alive():
            return
        _stop.clear()
        _started = True
        _thread = threading.Thread(target=_run, name="appointment-missed-check", daemon=True)
        _thread.start()


def stop_scheduler():
    global _started, _thread
    _stop.set()
    thread = _thread
    if thread is not None and thread.is_alive() and thread is not threading.current_thread():
        thread.join(timeout=5)
    with _start_lock:
        _started = False
        _thread = None
