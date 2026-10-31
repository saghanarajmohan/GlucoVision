import os
import unittest
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models import Appointment, HealthCentre, Hospital, Notification, Patient, Screening
from backend import appointment_scheduler
from backend.appointment_scheduler import process_missed_appointments, process_unattended_referrals, clinic_local_datetime, clinic_timezone
os.environ["GLUCOVISION_SKIP_SCHEMA_INIT"] = "1"
from backend import main


class MissedAppointmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.engine = create_engine(f"sqlite:///{self.tmp.name}/test.db")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.db = self.Session()
        self.hospital = Hospital(name="Hospital")
        self.db.add(self.hospital)
        self.db.flush()
        self.centre = HealthCentre(name="Centre", assigned_hospital_id=self.hospital.id)
        self.db.add(self.centre)
        self.db.flush()
        self.patient = Patient(patient_code="GV-00001", name="Patient One", phone="9990001111", health_centre_id=self.centre.id)
        self.db.add(self.patient)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        self.tmp.cleanup()

    def appointment(self, *, start, end=None, status="SCHEDULED", screening=None):
        row = Appointment(
            patient_id=self.patient.id,
            hospital_id=self.hospital.id,
            health_centre_id=self.centre.id,
            doctor_name="Staff",
            appointment_datetime=start,
            appointment_end_datetime=end,
            status=status,
            screening=screening,
        )
        self.db.add(row)
        self.db.commit()
        return row

    def run_at(self, instant, zone="Asia/Kolkata", grace=15):
        with patch.dict(os.environ, {"APP_TIMEZONE": zone, "APPOINTMENT_DURATION_MINUTES": "30"}):
            return process_missed_appointments(now=instant, grace_minutes=grace, session_factory=self.Session)

    def test_due_unattended_is_missed_once_and_notifies_once(self):
        row = self.appointment(start=datetime(2026, 5, 1, 10), end=datetime(2026, 5, 1, 5, 0))
        before_day_end = datetime(2026, 5, 1, 18, 44, 59, tzinfo=timezone.utc)  # 00:14:59 on May 2 in India
        self.assertEqual(self.run_at(before_day_end), 0)
        self.db.refresh(row)
        self.assertEqual(row.status, "SCHEDULED")
        after_day_end_and_grace = datetime(2026, 5, 1, 18, 45, tzinfo=timezone.utc)  # 00:15 on May 2 in India
        self.assertEqual(self.run_at(after_day_end_and_grace), 1)
        self.assertEqual(self.run_at(after_day_end_and_grace), 0)
        self.db.refresh(row)
        self.assertEqual(row.status, "MISSED")
        self.assertIsNotNone(row.missed_detected_at)
        self.assertEqual(self.db.query(Notification).filter_by(appointment_id=row.id).count(), 1)
        note = self.db.query(Notification).filter_by(appointment_id=row.id).one()
        self.assertEqual(note.health_centre_id, self.centre.id)
        self.assertIn("Patient One", note.message)
        self.assertIn("9990001111", note.message)

    def test_appointment_remains_scheduled_until_day_end_and_grace_boundary(self):
        future = self.appointment(start=datetime(2026, 5, 1, 12), end=datetime(2026, 5, 1, 7, 30))
        due_start = self.appointment(start=datetime(2026, 5, 1, 10), end=datetime(2026, 5, 1, 5, 0))
        self.run_at(datetime(2026, 5, 1, 18, 44, 59, tzinfo=timezone.utc))
        self.db.refresh(future)
        self.db.refresh(due_start)
        self.assertEqual(future.status, "SCHEDULED")
        self.assertEqual(due_start.status, "SCHEDULED")
        self.run_at(datetime(2026, 5, 1, 18, 45, tzinfo=timezone.utc))
        self.db.refresh(due_start)
        self.assertEqual(due_start.status, "MISSED")

    def create_via_health_centre_endpoint(self, appointment_datetime):
        staff = SimpleNamespace(
            role="HEALTH_CENTRE",
            health_centre_id=self.centre.id,
            name="Staff",
        )
        payload = main.LocalAppointmentCreate(
            patient_id=self.patient.id,
            appointment_datetime=appointment_datetime,
            appointment_type="Follow-up",
        )
        with patch.object(main, "SessionLocal", self.Session), \
             patch.object(appointment_scheduler, "SessionLocal", self.Session), \
             patch.object(main, "_authenticated_user", return_value=staff), \
             patch.dict(os.environ, {"APP_TIMEZONE": "Asia/Kolkata", "APPOINTMENT_GRACE_MINUTES": "15", "APPOINTMENT_DURATION_MINUTES": "30"}):
            return main.create_local_appointment(payload)

    def test_creating_past_appointment_marks_missed_and_persists_notification(self):
        # Interpret the input as clinic wall time, independently of the machine zone.
        now_local = datetime.now(clinic_timezone()).replace(tzinfo=None)
        response = self.create_via_health_centre_endpoint(now_local - timedelta(days=1))

        appointment_id = response["appointment"]["id"]
        row = self.db.query(Appointment).filter_by(id=appointment_id).one()
        self.assertEqual(response["appointment"]["status"], "MISSED")
        self.assertEqual(row.status, "MISSED")
        self.assertIsNotNone(row.missed_detected_at)
        notice = self.db.query(Notification).filter_by(
            appointment_id=appointment_id,
            notification_type="MISSED_APPOINTMENT",
        ).one()
        self.assertEqual(notice.health_centre_id, self.centre.id)
        self.assertEqual(process_missed_appointments(session_factory=self.Session), 0)
        self.assertEqual(self.db.query(Notification).filter_by(appointment_id=appointment_id).count(), 1)

    def test_creating_future_appointment_remains_scheduled_without_notification(self):
        now_local = datetime.now(clinic_timezone()).replace(tzinfo=None)
        response = self.create_via_health_centre_endpoint(now_local + timedelta(days=1))

        appointment_id = response["appointment"]["id"]
        row = self.db.query(Appointment).filter_by(id=appointment_id).one()
        self.assertEqual(response["appointment"]["status"], "SCHEDULED")
        self.assertEqual(row.status, "SCHEDULED")
        self.assertEqual(self.db.query(Notification).filter_by(appointment_id=appointment_id).count(), 0)

    def test_creating_appointment_inside_grace_period_remains_scheduled(self):
        now_local = datetime.now(clinic_timezone()).replace(tzinfo=None)
        # Even when the scheduled time has passed, the entire clinic-local date
        # must pass before missed detection starts its configured grace period.
        response = self.create_via_health_centre_endpoint(now_local - timedelta(minutes=35))

        appointment_id = response["appointment"]["id"]
        row = self.db.query(Appointment).filter_by(id=appointment_id).one()
        self.assertEqual(response["appointment"]["status"], "SCHEDULED")
        self.assertEqual(row.status, "SCHEDULED")
        self.assertEqual(self.db.query(Notification).filter_by(appointment_id=appointment_id).count(), 0)

    def test_attended_completed_screening_and_cancelled_appointments_are_untouched(self):
        completed = Screening(patient_id=self.patient.id, health_centre_id=self.centre.id, status="COMPLETED")
        self.db.add(completed)
        self.db.commit()
        attended = self.appointment(start=datetime(2026, 5, 1, 10), status="ATTENDED")
        cancelled = self.appointment(start=datetime(2026, 5, 1, 10), status="CANCELLED")
        screened = self.appointment(start=datetime(2026, 5, 1, 10), screening=completed)
        self.run_at(datetime(2026, 5, 1, 18, tzinfo=timezone.utc), grace=0)
        for row in (attended, cancelled, screened):
            self.db.refresh(row)
            self.assertNotEqual(row.status, "MISSED")
        self.assertEqual(self.db.query(Notification).count(), 0)

    def test_rescheduled_appointment_uses_current_database_time(self):
        row = self.appointment(start=datetime(2026, 5, 1, 10), end=datetime(2026, 5, 1, 5, 0))
        row.appointment_datetime = datetime(2026, 5, 2, 15)
        row.appointment_end_datetime = datetime(2026, 5, 2, 9, 30)
        self.db.commit()
        self.run_at(datetime(2026, 5, 2, 18, tzinfo=timezone.utc), grace=0)
        self.db.refresh(row)
        self.assertEqual(row.status, "SCHEDULED")

    def test_timezone_and_machine_local_zone_do_not_change_utc_decision(self):
        # 10:00 New York local time on the DST transition day is 14:00 UTC.
        row = self.appointment(start=datetime(2026, 3, 8, 10), end=datetime(2026, 3, 8, 14, 30))
        instant = datetime(2026, 3, 9, 4, 15, tzinfo=timezone.utc)
        with patch.dict(os.environ, {"APP_TIMEZONE": "America/New_York"}), patch("time.tzname", ("PST", "PDT")):
            process_missed_appointments(now=instant, grace_minutes=15, session_factory=self.Session)
        self.db.refresh(row)
        self.assertEqual(row.status, "MISSED")

    def test_nonexistent_daylight_saving_wall_time_is_rejected(self):
        with patch.dict(os.environ, {"APP_TIMEZONE": "America/New_York"}):
            with self.assertRaisesRegex(ValueError, "does not exist"):
                clinic_local_datetime(datetime(2026, 3, 8, 2, 30))

    def referral(self, submitted_at):
        row = Screening(patient_id=self.patient.id, health_centre_id=self.centre.id,
            routed_hospital_id=self.hospital.id, submitted_at=submitted_at,
            submitted_to_hospital="YES", prediction="Moderate DR", retinal_image_path="",
            confidence="90", probabilities="{}", gradcam_image_path="")
        self.db.add(row); self.db.commit()
        return row

    def test_referral_alert_waits_five_days_and_is_idempotent(self):
        with patch.dict(os.environ, {"APP_TIMEZONE": "Asia/Kolkata"}):
            submitted = datetime(2026, 5, 1, 6, 30)  # 12:00 clinic time, persisted as UTC naive
            row = self.referral(submitted)
            self.assertEqual(process_unattended_referrals(now=datetime(2026, 5, 6, 6, 29, tzinfo=timezone.utc), session_factory=self.Session), 0)
            self.assertEqual(process_unattended_referrals(now=datetime(2026, 5, 6, 6, 30, tzinfo=timezone.utc), session_factory=self.Session), 1)
            self.assertEqual(process_unattended_referrals(now=datetime(2026, 5, 7, 6, 30, tzinfo=timezone.utc), session_factory=self.Session), 0)
        notice = self.db.query(Notification).filter_by(referral_screening_id=row.id).one()
        self.assertEqual(notice.health_centre_id, self.centre.id)

    def test_referral_notification_is_independent_from_missed_appointment(self):
        with patch.dict(os.environ, {"APP_TIMEZONE": "Asia/Kolkata"}):
            row = self.referral(datetime(2026, 5, 1, 6, 30))
            appointment = self.appointment(start=datetime(2026, 5, 1, 10), end=datetime(2026, 5, 1, 5), screening=row)
            now = datetime(2026, 5, 7, 6, 30, tzinfo=timezone.utc)
            process_missed_appointments(now=now, grace_minutes=0, session_factory=self.Session)
            process_unattended_referrals(now=now, session_factory=self.Session)
            self.assertEqual(self.db.query(Notification).filter_by(appointment_id=appointment.id).count(), 1)
            self.assertEqual(self.db.query(Notification).filter_by(referral_screening_id=row.id).count(), 1)

    def test_attendance_before_deadline_prevents_referral_alert(self):
        with patch.dict(os.environ, {"APP_TIMEZONE": "Asia/Kolkata"}):
            row = self.referral(datetime(2026, 5, 1, 6, 30))
            row.hospital_attended_at = datetime(2026, 5, 5, 8)
            self.db.commit()
            self.assertEqual(process_unattended_referrals(now=datetime(2026, 5, 8, tzinfo=timezone.utc), session_factory=self.Session), 0)
            self.assertEqual(self.db.query(Notification).filter_by(referral_screening_id=row.id).count(), 0)

    def test_scheduler_start_is_idempotent_and_does_not_need_a_browser(self):
        with patch.object(appointment_scheduler, "_started", False), patch.object(appointment_scheduler.threading, "Thread") as thread:
            appointment_scheduler.start_scheduler()
            appointment_scheduler.start_scheduler()
            thread.assert_called_once_with(target=appointment_scheduler._run, name="appointment-missed-check", daemon=True)
            thread.return_value.start.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
