import os
import unittest
from datetime import datetime, timedelta
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models import Appointment, HealthCentre, Hospital, NetworkAudit, Notification, Patient, Screening, User
from backend.auth import verify_password
os.environ["GLUCOVISION_SKIP_SCHEMA_INIT"] = "1"
from backend import main, appointment_scheduler
from backend.appointment_scheduler import process_missed_appointments


class HospitalNetworkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.engine = create_engine(f"sqlite:///{self.tmp.name}/network.db")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.db = self.Session()
        self.admin = SimpleNamespace(id=90, role="SUPER_ADMIN", hospital_id=None, health_centre_id=None, name="Network Admin")
        self.hospital_user = SimpleNamespace(id=91, role="HOSPITAL_ADMIN", hospital_id=None, health_centre_id=None, name="Hospital Admin")
        self.hospital_a = Hospital(name="Hospital A", code="HA", is_active=True)
        self.hospital_b = Hospital(name="Hospital B", code="HB", is_active=True)
        self.db.add_all([self.hospital_a, self.hospital_b]); self.db.flush()
        self.hospital_user.hospital_id = self.hospital_a.id
        self.patient = None
        self.db.commit()

    def tearDown(self):
        self.db.close(); self.engine.dispose(); self.tmp.cleanup()

    def call_as_admin(self, fn, *args, **kwargs):
        with patch.object(main, "SessionLocal", self.Session), patch.object(main, "_authenticated_user", return_value=self.admin):
            return fn(*args, authorization="Bearer test", **kwargs)

    def centre(self, code, name, hospital_id):
        payload = main.HealthCentrePayload(name=name, code=code, assigned_hospital_id=hospital_id, district="Thanjavur", state="Tamil Nadu")
        return self.call_as_admin(main.create_health_centre, payload)["health_centre"]

    def test_create_hospital_and_reject_duplicate_code(self):
        payload = main.HospitalPayload(name="New Hospital", code="NH", district="A", state="B")
        created = self.call_as_admin(main.create_hospital, payload)
        self.assertEqual(created["hospital"]["code"], "NH")
        with self.assertRaises(HTTPException) as raised:
            self.call_as_admin(main.create_hospital, payload)
        self.assertEqual(raised.exception.status_code, 409)

    def test_health_centre_filters_use_trimmed_case_insensitive_district_and_and_logic(self):
        self.db.add_all([
            HealthCentre(name="Coimbatore A", code="CO1", district=" Coimbatore ", assigned_hospital_id=self.hospital_a.id),
            HealthCentre(name="Coimbatore B", code="CO2", district="coimbatore", assigned_hospital_id=self.hospital_b.id),
            HealthCentre(name="Chennai", code="CH1", district="Chennai", assigned_hospital_id=self.hospital_a.id),
            HealthCentre(name="Unassigned", code="UN1", district="Coimbatore"),
        ])
        self.db.commit()
        with patch.object(main, "SessionLocal", self.Session), patch.object(main, "_authenticated_user", return_value=self.admin):
            by_district = main.admin_health_centres(district=" COIMBATORE ", authorization="Bearer test")
            by_hospital = main.admin_health_centres(hospital_id=self.hospital_a.id, authorization="Bearer test")
            combined = main.admin_health_centres(hospital_id=self.hospital_a.id, district="coimbatore", authorization="Bearer test")
            unassigned = main.admin_health_centres(unassigned=True, district="Coimbatore", authorization="Bearer test")
            empty = main.admin_health_centres(hospital_id=self.hospital_b.id, district="Chennai", authorization="Bearer test")
        self.assertEqual({row["code"] for row in by_district["health_centres"]}, {"CO1", "CO2", "UN1"})
        self.assertEqual({row["code"] for row in by_hospital["health_centres"]}, {"CO1", "CH1"})
        self.assertEqual([row["code"] for row in combined["health_centres"]], ["CO1"])
        self.assertEqual([row["code"] for row in unassigned["health_centres"]], ["UN1"])
        self.assertEqual(empty["health_centres"], [])
        self.assertEqual(empty["count"], 0)

    def test_admin_can_create_unique_scoped_accounts_with_hashed_passwords(self):
        centre = HealthCentre(name="Account Centre", code="AC1")
        self.db.add(centre); self.db.commit()
        payload = main.OrganisationAccountPayload(username="centre.login", name="Centre Admin", password="a long secure password")
        created = self.call_as_admin(main.create_organisation_account, "health-centre", centre.id, payload)
        account = self.db.query(User).filter_by(username="centre.login").one()
        self.assertEqual(account.role, "HEALTH_CENTRE_USER")
        self.assertEqual(account.health_centre_id, centre.id)
        self.assertIsNone(account.hospital_id)
        self.assertTrue(verify_password(payload.password, account.password_hash))
        self.assertNotIn("password", created["account"])
        self.assertNotIn("password_hash", str(created))
        with patch.object(main, "SessionLocal", self.Session), patch.dict("os.environ", {"APP_SIGNING_SECRET": "test-signing-secret"}):
            logged_in = main.login(main.LoginRequest(username=payload.username, password=payload.password))
        self.assertEqual((logged_in["role"], logged_in["health_centre_id"]), ("HEALTH_CENTRE_USER", centre.id))
        self.assertNotIn("password_hash", logged_in)
        with self.assertRaises(HTTPException) as raised:
            self.call_as_admin(main.create_organisation_account, "health-centre", centre.id, payload)
        self.assertEqual(raised.exception.status_code, 409)

    def test_disabled_account_cannot_login_and_wrong_password_is_rejected(self):
        from backend.auth import hash_password
        account = User(name="Hospital Admin", username="hospital.login", password_hash=hash_password("correct secure password"), role="HOSPITAL_ADMIN", hospital_id=self.hospital_a.id)
        self.db.add(account); self.db.commit()
        with patch.object(main, "SessionLocal", self.Session), patch.dict("os.environ", {"APP_SIGNING_SECRET": "test-signing-secret"}):
            with self.assertRaises(HTTPException) as wrong:
                main.login(main.LoginRequest(username=account.username, password="wrong password"))
            self.assertEqual(wrong.exception.status_code, 401)
            result = main.login(main.LoginRequest(username=account.username, password="correct secure password"))
            self.assertEqual(result["role"], "HOSPITAL_ADMIN")
            account.is_active = False; self.db.commit()
            with self.assertRaises(HTTPException) as disabled:
                main.login(main.LoginRequest(username=account.username, password="correct secure password"))
            self.assertEqual(disabled.exception.status_code, 403)

    def test_multiple_centres_share_assignment_and_duplicate_code_is_rejected(self):
        first = self.centre("C1", "Centre One", self.hospital_a.id)
        second = self.centre("C2", "Centre Two", self.hospital_a.id)
        self.assertEqual(first["assigned_hospital_id"], second["assigned_hospital_id"])
        duplicate = main.HealthCentrePayload(name="Duplicate", code="C1", assigned_hospital_id=self.hospital_a.id)
        with self.assertRaises(HTTPException) as raised:
            self.call_as_admin(main.create_health_centre, duplicate)
        self.assertEqual(raised.exception.status_code, 409)

    def test_reassignment_preserves_report_hospital_snapshot(self):
        centre = self.centre("C3", "Centre Three", self.hospital_a.id)
        patient = Patient(patient_code="P1", name="Patient", health_centre_id=centre["id"])
        self.db.add(patient); self.db.flush()
        report = Screening(patient_id=patient.id, health_centre_id=centre["id"], routed_hospital_id=self.hospital_a.id, review_status="PENDING", prediction="Moderate DR")
        self.db.add(report); self.db.commit()
        payload = main.HealthCentrePayload(name="Centre Three", code="C3", assigned_hospital_id=self.hospital_b.id)
        self.call_as_admin(main.update_health_centre, centre["id"], payload)
        self.db.refresh(report)
        self.assertEqual(report.routed_hospital_id, self.hospital_a.id)
        audit = self.db.query(NetworkAudit).filter_by(action="HEALTH_CENTRE_REASSIGNED").one()
        self.assertEqual((audit.old_hospital_id, audit.new_hospital_id), (self.hospital_a.id, self.hospital_b.id))

    def test_assignment_routes_reports_that_were_waiting_without_rewriting_routed_history(self):
        centre = HealthCentre(name="Centre Waiting", code="C10")
        self.db.add(centre); self.db.flush()
        patient = Patient(patient_code="P10", name="Patient", health_centre_id=centre.id)
        self.db.add(patient); self.db.flush()
        waiting = Screening(patient_id=patient.id, health_centre_id=centre.id, review_status="AWAITING_ASSIGNMENT", prediction="Mild DR")
        self.db.add(waiting); self.db.commit()
        payload = main.HealthCentrePayload(name=centre.name, code=centre.code, assigned_hospital_id=self.hospital_a.id)
        self.call_as_admin(main.update_health_centre, centre.id, payload)
        self.db.refresh(waiting)
        self.assertEqual((waiting.routed_hospital_id, waiting.review_status), (self.hospital_a.id, "PENDING"))

    def test_report_routes_to_current_hospital_or_awaits_assignment(self):
        centre = HealthCentre(name="Assigned", code="C4", assigned_hospital_id=self.hospital_a.id)
        unassigned = HealthCentre(name="Unassigned", code="C5")
        self.db.add_all([centre, unassigned]); self.db.flush()
        assigned_report = main._route_screening(self.db, Screening(health_centre_id=centre.id))
        waiting_report = main._route_screening(self.db, Screening(health_centre_id=unassigned.id))
        self.assertEqual((assigned_report.routed_hospital_id, assigned_report.review_status), (self.hospital_a.id, "PENDING"))
        self.assertEqual((waiting_report.routed_hospital_id, waiting_report.review_status), (None, "AWAITING_ASSIGNMENT"))

    def test_health_centre_staff_cannot_change_centre_scope_or_manage_network(self):
        staff = SimpleNamespace(id=92, role="HEALTH_CENTRE_STAFF", health_centre_id=12, hospital_id=None)
        with self.assertRaises(HTTPException) as raised:
            main._require_health_centre_staff(staff, 13, self.db)
        self.assertEqual(raised.exception.status_code, 403)

    def test_health_centre_patient_listing_is_scoped_to_its_own_centre(self):
        centre_a = HealthCentre(name="Centre A", code="SCOPE-A")
        centre_b = HealthCentre(name="Centre B", code="SCOPE-B")
        self.db.add_all([centre_a, centre_b]); self.db.flush()
        self.db.add_all([
            Patient(patient_code="SCOPE-P1", name="Own Patient", health_centre_id=centre_a.id),
            Patient(patient_code="SCOPE-P2", name="Other Patient", health_centre_id=centre_b.id),
        ])
        self.db.commit()
        staff = SimpleNamespace(id=92, role="HEALTH_CENTRE_USER", health_centre_id=centre_a.id, hospital_id=None)
        with patch.object(main, "SessionLocal", self.Session), patch.object(main, "_authenticated_user", return_value=staff):
            own = main.list_patients(centre_a.id, authorization="Bearer test")
            with self.assertRaises(HTTPException) as raised:
                main.list_patients(centre_b.id, authorization="Bearer test")
        self.assertEqual([row["name"] for row in own["patients"]], ["Own Patient"])
        self.assertEqual(raised.exception.status_code, 403)
        with patch.object(main, "SessionLocal", self.Session), patch.object(main, "_authenticated_user", return_value=staff):
            with self.assertRaises(HTTPException) as raised:
                main.admin_overview(authorization="Bearer test")
        self.assertEqual(raised.exception.status_code, 403)

    def test_health_centre_screening_history_is_scoped_to_its_own_centre(self):
        centre_a = HealthCentre(name="History A", code="HIST-A", assigned_hospital_id=self.hospital_a.id)
        centre_b = HealthCentre(name="History B", code="HIST-B", assigned_hospital_id=self.hospital_b.id)
        self.db.add_all([centre_a, centre_b]); self.db.flush()
        patient_a = Patient(patient_code="HIST-P1", name="History Patient A", age=56, sex="Female", phone="9990001122", health_centre_id=centre_a.id)
        patient_b = Patient(patient_code="HIST-P2", name="History Patient B", health_centre_id=centre_b.id)
        self.db.add_all([patient_a, patient_b]); self.db.flush()
        self.db.add_all([
            Screening(patient_id=patient_a.id, health_centre_id=centre_a.id, submitted_to_hospital="YES", prediction="Moderate DR",
                confidence="92.5", probabilities='{"Moderate DR": 92.5}', original_report_pdf_path="screenings/101/original_report.pdf",
                retinal_image_path="screenings/101/retinal.jpg", original_heatmap_path="screenings/101/gradcam.jpg"),
            Screening(patient_id=patient_b.id, health_centre_id=centre_b.id, submitted_to_hospital="YES", prediction="Severe DR"),
        ]); self.db.commit()
        staff = SimpleNamespace(id=95, role="HEALTH_CENTRE_USER", health_centre_id=centre_a.id, hospital_id=None)
        with patch.object(main, "SessionLocal", self.Session), patch.object(main, "_authenticated_user", return_value=staff):
            own = main.health_centre_screenings(centre_a.id, authorization="Bearer test")
            with self.assertRaises(HTTPException) as denied:
                main.health_centre_screenings(centre_b.id, authorization="Bearer test")
        self.assertEqual([row["patient_name"] for row in own["screenings"]], ["History Patient A"])
        item = own["screenings"][0]
        self.assertEqual((item["patient_age"], item["patient_sex"], item["patient_phone"]), (56, "Female", "9990001122"))
        self.assertEqual((item["confidence"], item["probabilities"]), ("92.5", {"Moderate DR": 92.5}))
        self.assertEqual(item["original_pdf_url"], f"/screening/{item['screening_id']}/original-pdf")
        self.assertEqual(item["original_image_url"], f"/screening/{item['screening_id']}/original-image")
        self.assertEqual(item["gradcam_image_path"], f"/screening/{item['screening_id']}/heatmap")
        self.assertEqual(denied.exception.status_code, 403)

    def test_hospital_statistics_are_database_counts(self):
        centre = HealthCentre(name="Centre", code="C9", assigned_hospital_id=self.hospital_a.id)
        self.db.add(centre); self.db.flush()
        patient = Patient(patient_code="P9", name="Patient", health_centre_id=centre.id)
        self.db.add(patient); self.db.flush()
        self.db.add(Screening(patient_id=patient.id, health_centre_id=centre.id, routed_hospital_id=self.hospital_a.id, submitted_to_hospital="YES", review_status="PENDING", prediction="Severe DR"))
        self.db.commit()
        with patch.object(main, "SessionLocal", self.Session), patch.object(main, "_authenticated_user", return_value=self.hospital_user):
            data = main.hospital_dashboard(authorization="Bearer test")
        self.assertEqual(data["stats"]["health_centres"], 1)
        self.assertEqual(data["stats"]["patients"], 1)
        self.assertEqual(data["stats"]["reports"], 1)
        self.assertEqual(data["stats"]["pending_reviews"], 1)
        self.assertEqual(data["stats"]["urgent"], 1)

    def test_hospital_inbox_and_review_are_isolated(self):
        centre = HealthCentre(name="Centre", code="C6", assigned_hospital_id=self.hospital_b.id)
        self.db.add(centre); self.db.flush()
        patient = Patient(patient_code="P2", name="Patient", health_centre_id=centre.id)
        self.db.add(patient); self.db.flush()
        report = Screening(patient_id=patient.id, health_centre_id=centre.id, routed_hospital_id=self.hospital_b.id, prediction="Severe DR", review_status="PENDING")
        self.db.add(report); self.db.commit()
        with patch.object(main, "SessionLocal", self.Session), patch.object(main, "_authenticated_user", return_value=self.hospital_user):
            dashboard = main.hospital_dashboard(authorization="Bearer test")
            self.assertEqual(dashboard["reports"], [])
            with self.assertRaises(HTTPException) as raised:
                main.review_routed_report(report.id, main.ReviewPayload(notes="Reviewed", flagged=True), authorization="Bearer test")
            self.assertEqual(raised.exception.status_code, 404)

    def test_hospital_review_keeps_ai_result_and_stores_clinical_assessment(self):
        centre = HealthCentre(name="Centre", code="C7", assigned_hospital_id=self.hospital_a.id)
        self.db.add(centre); self.db.flush()
        patient = Patient(patient_code="P3", name="Patient", health_centre_id=centre.id)
        self.db.add(patient); self.db.flush()
        report = Screening(patient_id=patient.id, health_centre_id=centre.id, routed_hospital_id=self.hospital_a.id, submitted_to_hospital="YES", prediction="Moderate DR", review_status="PENDING")
        self.db.add(report); self.db.commit()
        with patch.object(main, "SessionLocal", self.Session), patch.object(main, "_authenticated_user", return_value=self.hospital_user):
            result = main.review_routed_report(report.id, main.ReviewPayload(notes="Refer to ophthalmology", flagged=True), authorization="Bearer test")
        self.db.refresh(report)
        self.assertEqual(result["ai_prediction"], "Moderate DR")
        self.assertEqual(report.prediction, "Moderate DR")
        self.assertEqual(report.clinical_review_notes, "Refer to ophthalmology")
        self.assertTrue(report.clinically_flagged)

    def test_patient_category_requires_saved_clinical_disposition_and_never_changes_ai_result(self):
        centre = HealthCentre(name="Disposition Centre", code="DISP1", assigned_hospital_id=self.hospital_a.id)
        self.db.add(centre); self.db.flush()
        patient = Patient(patient_code="DISP-P1", name="Disposition Patient", health_centre_id=centre.id)
        self.db.add(patient); self.db.flush()
        report = Screening(patient_id=patient.id, health_centre_id=centre.id, routed_hospital_id=self.hospital_a.id,
            prediction="Moderate DR", confidence="73.25", submitted_to_hospital="YES", review_status="PENDING")
        self.db.add(report); self.db.commit()
        with patch.object(main, "SessionLocal", self.Session), patch.object(main, "_authenticated_user", return_value=self.hospital_user):
            with self.assertRaises(HTTPException) as early_disposition:
                main.set_clinical_disposition(report.id, main.ClinicalDispositionPayload(disposition="DISCHARGED_CARE_COMPLETED", clinical_outcome="RECOVERED"), authorization="Bearer test")
            self.assertEqual(early_disposition.exception.status_code, 409)
            main.review_routed_report(report.id, main.ReviewPayload(doctor_name="Dr Clinician", notes="Assessment documented", recommendations="Care episode completed", clinical_disposition="DISCHARGED_CARE_COMPLETED", clinical_outcome="DISCHARGED_WITHOUT_DOCUMENTED_RECOVERY"), authorization="Bearer test")
            dashboard = main.hospital_dashboard(authorization="Bearer test")
        self.assertEqual(dashboard["reports"][0]["care_category"], "RECOVERED_DISCHARGED")
        self.assertEqual(dashboard["reports"][0]["clinical_disposition"], "DISCHARGED_CARE_COMPLETED")
        self.assertEqual(dashboard["reports"][0]["clinical_outcome"], "DISCHARGED_WITHOUT_DOCUMENTED_RECOVERY")
        self.assertEqual(report.prediction, "Moderate DR")

    def test_three_dispositions_persist_and_route_to_their_saved_care_categories(self):
        centre = HealthCentre(name="Three Dispositions", code="3DISP", assigned_hospital_id=self.hospital_a.id)
        self.db.add(centre); self.db.flush()
        definitions = [
            ("FUP-P1", "FOLLOW_UP_REQUIRED", None, "Follow up in two weeks", True, "FOLLOW_UP_REQUIRED", None),
            ("FUP-P2", "STABLE_MONITORING", None, "Repeat examination in three months", True, "FOLLOW_UP_REQUIRED", None),
            ("FUP-P3", "DISCHARGED_CARE_COMPLETED", "RECOVERED", "Care episode complete", False, "RECOVERED_DISCHARGED", "RECOVERED"),
        ]
        reports = []
        next_visit = datetime.now(main.clinic_timezone()).replace(tzinfo=None) + timedelta(days=14)
        for code, disposition, outcome, plan, follow_up_required, expected_category, _ in definitions:
            patient = Patient(patient_code=code, name=code, health_centre_id=centre.id)
            self.db.add(patient); self.db.flush()
            report = Screening(patient_id=patient.id, health_centre_id=centre.id,
                routed_hospital_id=self.hospital_a.id, prediction="Moderate DR", submitted_to_hospital="YES")
            self.db.add(report); self.db.commit(); self.db.refresh(report)
            reports.append((report, disposition, outcome, plan, follow_up_required, expected_category))
        with patch.object(main, "SessionLocal", self.Session), patch.object(main, "_authenticated_user", return_value=self.hospital_user):
            for report, disposition, outcome, plan, follow_up_required, _ in reports:
                review_payload = main.ReviewPayload(
                    doctor_name="Dr Review", notes="Assessment recorded", recommendations=plan,
                    clinical_disposition=disposition, clinical_outcome=outcome,
                    follow_up_required=follow_up_required,
                    appointment_datetime=next_visit if disposition in {"FOLLOW_UP_REQUIRED", "STABLE_MONITORING"} else None)
                saved = main.review_routed_report(report.id, review_payload, authorization="Bearer test")
                self.assertEqual(saved["ai_prediction"], "Moderate DR")
                if disposition in {"FOLLOW_UP_REQUIRED", "STABLE_MONITORING"}:
                    self.assertIsNotNone(saved["appointment"])
                    main.review_routed_report(report.id, review_payload, authorization="Bearer test")
            dashboard = main.hospital_dashboard(authorization="Bearer test")
        by_id = {item["id"]: item for item in dashboard["reports"]}
        for report, disposition, outcome, _plan, follow_up_required, expected_category in reports:
            saved = by_id[report.id]
            self.assertEqual(saved["clinical_disposition"], disposition)
            self.assertEqual(saved["clinical_outcome"], outcome)
            self.assertEqual(saved["follow_up_required"], follow_up_required)
            self.assertEqual(saved["care_category"], expected_category)
            self.assertEqual(report.prediction, "Moderate DR")
        self.assertEqual(self.db.query(Appointment).filter(Appointment.screening_id.in_([r.id for r, *_ in reports])).count(), 2)

    def test_stable_monitoring_requires_a_documented_plan_and_follow_up_selection(self):
        centre = HealthCentre(name="Stable Validation", code="STAB1", assigned_hospital_id=self.hospital_a.id)
        self.db.add(centre); self.db.flush()
        patient = Patient(patient_code="STAB-P1", name="Stable Patient", health_centre_id=centre.id)
        self.db.add(patient); self.db.flush()
        report = Screening(patient_id=patient.id, health_centre_id=centre.id,
            routed_hospital_id=self.hospital_a.id, submitted_to_hospital="YES")
        self.db.add(report); self.db.commit()
        with patch.object(main, "SessionLocal", self.Session), patch.object(main, "_authenticated_user", return_value=self.hospital_user):
            with self.assertRaises(HTTPException) as missing_selection:
                main.review_routed_report(report.id, main.ReviewPayload(doctor_name="Dr Review",
                    clinical_disposition="STABLE_MONITORING", follow_up_required=False,
                    notes="Stable assessment", recommendations="Review in three months",
                    appointment_datetime=datetime.now(main.clinic_timezone()).replace(tzinfo=None) + timedelta(days=30)), authorization="Bearer test")
            self.assertEqual(missing_selection.exception.status_code, 422)
            with self.assertRaises(HTTPException) as missing_plan:
                main.review_routed_report(report.id, main.ReviewPayload(doctor_name="Dr Review",
                    clinical_disposition="STABLE_MONITORING", follow_up_required=True,
                    notes="Stable assessment", recommendations="",
                    appointment_datetime=datetime.now(main.clinic_timezone()).replace(tzinfo=None) + timedelta(days=30)), authorization="Bearer test")
            self.assertEqual(missing_plan.exception.status_code, 422)
            for disposition in ("FOLLOW_UP_REQUIRED", "STABLE_MONITORING"):
                with self.assertRaises(HTTPException) as missing_date:
                    main.review_routed_report(report.id, main.ReviewPayload(doctor_name="Dr Review",
                        notes="Assessment documented", recommendations="Review in three months",
                        clinical_disposition=disposition, follow_up_required=True), authorization="Bearer test")
                self.assertEqual(missing_date.exception.status_code, 422)
            with self.assertRaises(HTTPException) as invalid_date:
                main.review_routed_report(report.id, main.ReviewPayload(doctor_name="Dr Review",
                    notes="Assessment documented", recommendations="Return soon",
                    clinical_disposition="FOLLOW_UP_REQUIRED", appointment_datetime=datetime.now(main.clinic_timezone()).replace(tzinfo=None) - timedelta(days=1)), authorization="Bearer test")
            self.assertEqual(invalid_date.exception.status_code, 422)
        self.assertIsNone(report.clinical_disposition)
        self.assertEqual(self.db.query(Appointment).filter_by(screening_id=report.id).count(), 0)

    def test_disposition_update_endpoint_also_requires_and_saves_next_appointment(self):
        centre = HealthCentre(name="Disposition Endpoint Centre", code="DEPC", assigned_hospital_id=self.hospital_a.id)
        self.db.add(centre); self.db.flush()
        patient = Patient(patient_code="DEPC-P1", name="Disposition Endpoint Patient", health_centre_id=centre.id)
        self.db.add(patient); self.db.flush()
        report = Screening(patient_id=patient.id, health_centre_id=centre.id, routed_hospital_id=self.hospital_a.id,
            submitted_to_hospital="YES", review_status="REVIEWED", clinical_reviewed_at=datetime.utcnow(),
            clinical_review_notes="Stable assessment", consulted_doctor="Dr Endpoint", doctor_notes="Repeat exam in three months")
        self.db.add(report); self.db.commit()
        future = datetime.now(main.clinic_timezone()).replace(tzinfo=None) + timedelta(days=90)
        with patch.object(main, "SessionLocal", self.Session), patch.object(main, "_authenticated_user", return_value=self.hospital_user):
            with self.assertRaises(HTTPException) as missing_appointment:
                main.set_clinical_disposition(report.id, main.ClinicalDispositionPayload(
                    disposition="STABLE_MONITORING", follow_up_required=True), authorization="Bearer test")
            self.assertEqual(missing_appointment.exception.status_code, 422)
            saved = main.set_clinical_disposition(report.id, main.ClinicalDispositionPayload(
                disposition="STABLE_MONITORING", follow_up_required=True,
                appointment_datetime=future), authorization="Bearer test")
        self.assertEqual(saved["clinical_disposition"], "STABLE_MONITORING")
        self.assertEqual(saved["appointment"]["status"], "SCHEDULED")
        self.assertEqual(self.db.query(Appointment).filter_by(screening_id=report.id).count(), 1)

    def test_legacy_dispositions_migrate_without_losing_outcome_or_notes(self):
        from sqlalchemy import create_engine
        migration_engine = create_engine("sqlite://")
        with migration_engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE screenings (id INTEGER PRIMARY KEY, clinical_disposition VARCHAR, clinical_outcome VARCHAR, follow_up_required BOOLEAN, doctor_notes TEXT)")
            connection.exec_driver_sql("INSERT INTO screenings VALUES (1, 'FOLLOW_UP', NULL, NULL, 'Return in two weeks')")
            connection.exec_driver_sql("INSERT INTO screenings VALUES (2, 'STABLE_MONITORING', NULL, NULL, 'Repeat examination in three months')")
            connection.exec_driver_sql("INSERT INTO screenings VALUES (3, 'STABLE_MONITORING', NULL, NULL, NULL)")
            connection.exec_driver_sql("INSERT INTO screenings VALUES (4, 'RECOVERED', NULL, NULL, 'Recovery documented')")
            connection.exec_driver_sql("INSERT INTO screenings VALUES (5, 'DISCHARGED', NULL, NULL, 'Discharged from care')")
            main._migrate_clinical_dispositions(connection)
            main._migrate_clinical_dispositions(connection)
            rows = connection.exec_driver_sql("SELECT id, clinical_disposition, clinical_outcome, follow_up_required, doctor_notes FROM screenings ORDER BY id").all()
        migration_engine.dispose()
        self.assertEqual(rows[0][1:4], ("FOLLOW_UP_REQUIRED", None, 1))
        self.assertEqual(rows[1][1:4], ("STABLE_MONITORING", None, 0))
        self.assertEqual(rows[2][1:4], ("STABLE_MONITORING", None, 0))
        self.assertEqual(rows[3][1:4], ("DISCHARGED_CARE_COMPLETED", "RECOVERED", 0))
        self.assertEqual(rows[4][1:4], ("DISCHARGED_CARE_COMPLETED", "DISCHARGED_WITHOUT_DOCUMENTED_RECOVERY", 0))
        self.assertEqual((rows[3][4], rows[4][4]), ("Recovery documented", "Discharged from care"))

    def test_hospital_dashboard_returns_full_report_details_and_scoped_next_appointment(self):
        centre = HealthCentre(name="Report Centre", code="RPT1", assigned_hospital_id=self.hospital_a.id)
        self.db.add(centre); self.db.flush()
        patient = Patient(patient_code="RPT-P1", name="Report Patient", age=51, sex="Female", health_centre_id=centre.id)
        self.db.add(patient); self.db.flush()
        report = Screening(patient_id=patient.id, health_centre_id=centre.id, routed_hospital_id=self.hospital_a.id,
            prediction="Moderate DR", confidence="0.91", probabilities='{"moderate": 0.91}',
            submitted_to_hospital="YES", review_status="PENDING", clinically_flagged=False)
        self.db.add(report); self.db.flush()
        appointment = Appointment(screening_id=report.id, patient_id=patient.id, hospital_id=self.hospital_a.id,
            health_centre_id=centre.id, doctor_name="Dr Example", appointment_datetime=datetime.now() + timedelta(days=4), status="SCHEDULED")
        self.db.add(appointment); self.db.commit()
        with patch.object(main, "SessionLocal", self.Session), patch.object(main, "_authenticated_user", return_value=self.hospital_user):
            dashboard = main.hospital_dashboard(authorization="Bearer test")
        item = dashboard["reports"][0]
        self.assertEqual((item["patient_name"], item["patient_code"], item["health_centre"]), ("Report Patient", "RPT-P1", "Report Centre"))
        self.assertEqual((item["patient_age"], item["patient_sex"], item["prediction"], item["confidence"]), (51, "Female", "Moderate DR", "0.91"))
        self.assertEqual(item["probabilities"], {"moderate": 0.91})
        self.assertEqual(item["appointment"]["id"], appointment.id)
        self.assertEqual(dashboard["appointments"][0]["patient_name"], "Report Patient")

    def test_review_can_be_edited_without_overwriting_ai_result(self):
        centre = HealthCentre(name="Clinical Centre", code="CL1", assigned_hospital_id=self.hospital_a.id)
        self.db.add(centre); self.db.flush()
        patient = Patient(patient_code="CL-P1", name="Clinical Patient", health_centre_id=centre.id)
        self.db.add(patient); self.db.flush()
        report = Screening(patient_id=patient.id, health_centre_id=centre.id, routed_hospital_id=self.hospital_a.id,
            prediction="Severe DR", confidence="0.88", submitted_to_hospital="YES", review_status="PENDING")
        self.db.add(report); self.db.commit()
        with patch.object(main, "SessionLocal", self.Session), patch.object(main, "_authenticated_user", return_value=self.hospital_user):
            main.review_routed_report(report.id, main.ReviewPayload(doctor_name="Dr A", notes="Assessment one", recommendations="Refer urgently", flagged=True), authorization="Bearer test")
            main.review_routed_report(report.id, main.ReviewPayload(doctor_name="Dr B", notes="Assessment updated", recommendations="Review in one week", flagged=False), authorization="Bearer test")
        self.db.refresh(report)
        self.assertEqual((report.prediction, report.confidence), ("Severe DR", "0.88"))
        self.assertEqual((report.review_status, report.consulted_doctor, report.clinical_review_notes, report.doctor_notes),
            ("REVIEWED", "Dr B", "Assessment updated", "Review in one week"))
        self.assertFalse(report.clinically_flagged)

    def test_hospital_scheduling_is_idempotent_scoped_and_manageable(self):
        centre = HealthCentre(name="Appointment Centre", code="APT1", assigned_hospital_id=self.hospital_a.id)
        self.db.add(centre); self.db.flush()
        patient = Patient(patient_code="APT-P1", name="Appointment Patient", health_centre_id=centre.id)
        self.db.add(patient); self.db.flush()
        report = Screening(patient_id=patient.id, health_centre_id=centre.id, routed_hospital_id=self.hospital_a.id,
            prediction="Mild DR", submitted_to_hospital="YES", review_status="PENDING")
        self.db.add(report); self.db.commit()
        future = datetime.now(main.clinic_timezone()).replace(tzinfo=None) + timedelta(days=5)
        payload = main.HospitalAppointmentCreate(appointment_datetime=future, doctor_name="Dr Schedule", notes="Bring prior records")
        with patch.object(main, "SessionLocal", self.Session), patch.object(main, "_authenticated_user", return_value=self.hospital_user):
            first = main.create_hospital_appointment(report.id, payload, authorization="Bearer test")
            second = main.create_hospital_appointment(report.id, payload, authorization="Bearer test")
            dashboard = main.hospital_dashboard(authorization="Bearer test")
            rescheduled_time = future + timedelta(days=2)
            rescheduled = main.update_hospital_appointment(first["appointment"]["id"], main.HospitalAppointmentUpdate(appointment_datetime=rescheduled_time), authorization="Bearer test")
            updated = main.update_hospital_appointment(first["appointment"]["id"], main.HospitalAppointmentUpdate(status="ATTENDED"), authorization="Bearer test")
        self.assertFalse(first["duplicate"])
        self.assertTrue(second["duplicate"])
        self.assertEqual(self.db.query(Appointment).filter_by(screening_id=report.id).count(), 1)
        self.assertEqual(dashboard["appointments"][0]["status"], "SCHEDULED")
        self.assertEqual(rescheduled["appointment"]["status"], "SCHEDULED")
        self.assertEqual(rescheduled["appointment"]["appointment_datetime"], rescheduled_time.replace(tzinfo=main.clinic_timezone()).isoformat())
        self.assertEqual(updated["appointment"]["status"], "ATTENDED")
        other_hospital_user = SimpleNamespace(id=93, role="HOSPITAL_ADMIN", hospital_id=self.hospital_b.id, health_centre_id=None, name="Other Hospital Admin")
        with patch.object(main, "SessionLocal", self.Session), patch.object(main, "_authenticated_user", return_value=other_hospital_user):
            with self.assertRaises(HTTPException) as cross_hospital:
                main.update_hospital_appointment(first["appointment"]["id"], main.HospitalAppointmentUpdate(status="CANCELLED"), authorization="Bearer test")
        self.assertEqual(cross_hospital.exception.status_code, 404)

    def test_rescheduling_missed_appointment_preserves_history_notification_and_disposition(self):
        centre = HealthCentre(name="Missed Reschedule Centre", code="MRSC", assigned_hospital_id=self.hospital_a.id)
        self.db.add(centre); self.db.flush()
        patient = Patient(patient_code="MRSC-P1", name="Missed Patient", health_centre_id=centre.id)
        self.db.add(patient); self.db.flush()
        report = Screening(patient_id=patient.id, health_centre_id=centre.id, routed_hospital_id=self.hospital_a.id,
            submitted_to_hospital="YES", review_status="REVIEWED", clinical_disposition="FOLLOW_UP_REQUIRED",
            follow_up_required=True, prediction="Moderate DR")
        self.db.add(report); self.db.flush()
        missed = Appointment(screening_id=report.id, patient_id=patient.id, hospital_id=self.hospital_a.id,
            health_centre_id=centre.id, doctor_name="Dr Follow-up", appointment_datetime=datetime(2020, 1, 1, 10), status="MISSED")
        self.db.add(missed); self.db.flush()
        notice = Notification(health_centre_id=centre.id, patient_id=patient.id, appointment_id=missed.id,
            assigned_hospital_id=self.hospital_a.id, notification_type="MISSED_APPOINTMENT", message="Missed consultation")
        self.db.add(notice); self.db.commit()
        future = datetime.now(main.clinic_timezone()).replace(tzinfo=None) + timedelta(days=8)
        payload = main.HospitalAppointmentUpdate(appointment_datetime=future, doctor_name="Dr Follow-up")
        with patch.object(main, "SessionLocal", self.Session), patch.object(main, "_authenticated_user", return_value=self.hospital_user):
            first = main.update_hospital_appointment(missed.id, payload, authorization="Bearer test")
            second = main.update_hospital_appointment(missed.id, payload, authorization="Bearer test")
        self.assertEqual(first["appointment"]["status"], "SCHEDULED")
        self.assertEqual(second["appointment"]["id"], first["appointment"]["id"])
        self.assertEqual(self.db.query(Appointment).filter_by(screening_id=report.id).count(), 2)
        self.db.refresh(missed); self.db.refresh(report)
        self.assertEqual(missed.status, "MISSED")
        self.assertEqual(report.clinical_disposition, "FOLLOW_UP_REQUIRED")
        self.assertEqual(self.db.query(Notification).filter_by(appointment_id=missed.id,
            notification_type="MISSED_APPOINTMENT").count(), 1)

    def test_single_screening_detail_requires_authentication_and_hospital_scope(self):
        centre = HealthCentre(name="Secure Centre", code="SEC1", assigned_hospital_id=self.hospital_a.id)
        self.db.add(centre); self.db.flush()
        patient = Patient(patient_code="SEC-P1", name="Secure Patient", health_centre_id=centre.id)
        self.db.add(patient); self.db.flush()
        report = Screening(patient_id=patient.id, health_centre_id=centre.id, routed_hospital_id=self.hospital_b.id, prediction="Mild DR")
        self.db.add(report); self.db.commit()
        with patch.object(main, "SessionLocal", self.Session):
            with self.assertRaises(HTTPException) as unauthenticated:
                main.get_screening(report.id, authorization=None)
        self.assertEqual(unauthenticated.exception.status_code, 401)
        with patch.object(main, "SessionLocal", self.Session), patch.object(main, "_authenticated_user", return_value=self.hospital_user):
            with self.assertRaises(HTTPException) as cross_hospital:
                main.get_screening(report.id, authorization="Bearer test")
        self.assertEqual(cross_hospital.exception.status_code, 404)

    def test_original_pdf_is_private_scoped_and_hash_matches_stored_bytes(self):
        import hashlib
        import os
        centre = HealthCentre(name="PDF Centre", code="PDF1", assigned_hospital_id=self.hospital_a.id)
        self.db.add(centre); self.db.flush()
        patient = Patient(patient_code="PDF-P1", name="PDF Patient", health_centre_id=centre.id)
        self.db.add(patient); self.db.flush()
        report = Screening(patient_id=patient.id, health_centre_id=centre.id, routed_hospital_id=self.hospital_a.id,
            original_report_pdf_path="screenings/1/original_report.pdf", submitted_to_hospital="YES", prediction="Mild DR")
        self.db.add(report); self.db.commit()
        report.original_report_pdf_path = f"screenings/{report.id}/original_report.pdf"; self.db.commit()
        with TemporaryDirectory(dir=os.getcwd()) as storage:
            with patch.dict(os.environ, {"GLUCOVISION_PRIVATE_STORAGE_DIR": storage}), patch.object(main, "SessionLocal", self.Session), patch.object(main, "_authenticated_user", return_value=self.hospital_user):
                from backend.report_files import write_private_file
                raw = b"%PDF-1.7\noriginal-screening-bytes"
                write_private_file(report.original_report_pdf_path, raw)
                response = main.get_original_screening_pdf(report.id, authorization="Bearer test")
                self.assertEqual(response.body, raw)
                self.assertEqual(response.headers["X-Content-SHA256"], hashlib.sha256(raw).hexdigest())
                centre_user = SimpleNamespace(id=93, role="HEALTH_CENTRE_USER", hospital_id=None, health_centre_id=centre.id, name="Centre Staff")
                with patch.object(main, "_authenticated_user", return_value=centre_user):
                    centre_response = main.get_original_screening_pdf(report.id, authorization="Bearer centre")
                self.assertEqual(centre_response.body, response.body)
                self.assertEqual(centre_response.headers["X-Content-SHA256"], response.headers["X-Content-SHA256"])
            other_user = SimpleNamespace(id=94, role="HOSPITAL_ADMIN", hospital_id=self.hospital_b.id, health_centre_id=None, name="Other")
            with patch.object(main, "SessionLocal", self.Session), patch.object(main, "_authenticated_user", return_value=other_user):
                with self.assertRaises(HTTPException) as denied:
                    main.get_original_screening_pdf(report.id, authorization="Bearer other")
            self.assertEqual(denied.exception.status_code, 404)

    def test_missed_appointment_notification_snapshots_assigned_hospital_once(self):
        centre = HealthCentre(name="Centre", code="C8", assigned_hospital_id=self.hospital_a.id)
        self.db.add(centre); self.db.flush()
        patient = Patient(patient_code="P4", name="Patient", health_centre_id=centre.id)
        self.db.add(patient); self.db.flush()
        report = Screening(patient_id=patient.id, health_centre_id=centre.id, routed_hospital_id=self.hospital_a.id,
            submitted_to_hospital="YES", prediction="Moderate DR")
        self.db.add(report); self.db.flush()
        appt = Appointment(screening_id=report.id, patient_id=patient.id, hospital_id=self.hospital_a.id,
            health_centre_id=centre.id, doctor_name="Staff", appointment_datetime=__import__("datetime").datetime(2020, 1, 1, 10), status="SCHEDULED")
        self.db.add(appt); self.db.commit()
        from datetime import datetime, timezone
        with patch.object(appointment_scheduler, "SessionLocal", self.Session):
            process_missed_appointments(now=datetime(2026, 1, 1, tzinfo=timezone.utc), session_factory=self.Session)
            process_missed_appointments(now=datetime(2026, 1, 1, tzinfo=timezone.utc), session_factory=self.Session)
        notification = self.db.query(Notification).filter_by(appointment_id=appt.id).one()
        self.assertEqual(notification.assigned_hospital_id, self.hospital_a.id)
        self.assertEqual(self.db.query(Notification).filter_by(appointment_id=appt.id).count(), 1)
        centre_user = SimpleNamespace(id=96, role="HEALTH_CENTRE_USER", health_centre_id=centre.id, hospital_id=None)
        with patch.object(main, "SessionLocal", self.Session), patch.object(main, "_authenticated_user", return_value=centre_user):
            alerts = main.get_health_centre_notifications(centre.id, authorization="Bearer centre")
        item = alerts["notifications"][0]
        self.assertEqual((item["report_id"], item["patient_name"], item["doctor_name"]), (report.id, "Patient", "Staff"))
        self.assertEqual((item["assigned_hospital"], item["appointment_status"]), ("Hospital A", "MISSED"))
        self.assertIsNotNone(item["appointment_datetime"])
        self.assertIsNotNone(item["missed_detected_at"])


if __name__ == "__main__":
    unittest.main()
