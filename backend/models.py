from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Boolean, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime

from backend.database import Base


# ============================================================
# USER
# ============================================================

class User(Base):
    __tablename__ = "users"

    id = Column(
        Integer,
        primary_key=True,
        index=True
    )

    name = Column(
        String,
        nullable=False
    )

    username = Column(
        String,
        unique=True,
        index=True,
        nullable=False
    )

    password_hash = Column(
        String,
        nullable=False
    )

    role = Column(
        String,
        nullable=False
    )

    hospital_id = Column(
        Integer,
        ForeignKey("hospitals.id"),
        nullable=True
    )

    health_centre_id = Column(
        Integer,
        ForeignKey("health_centres.id"),
        nullable=True
    )

    is_active = Column(Boolean, nullable=False, default=True)


# ============================================================
# HOSPITAL
# ============================================================

class Hospital(Base):
    __tablename__ = "hospitals"

    id = Column(
        Integer,
        primary_key=True,
        index=True
    )

    name = Column(
        String,
        nullable=False
    )

    code = Column(String, unique=True, index=True, nullable=True)
    district = Column(String, nullable=True)
    state = Column(String, nullable=True)
    address = Column(Text, nullable=True)
    contact_number = Column(String, nullable=True)
    official_email = Column(String, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)

    location = Column(
        String
    )

    health_centres = relationship(
        "HealthCentre",
        back_populates="hospital"
    )

    appointments = relationship(
        "Appointment",
        back_populates="hospital"
    )


# ============================================================
# HEALTH CENTRE
# ============================================================

class HealthCentre(Base):
    __tablename__ = "health_centres"

    id = Column(
        Integer,
        primary_key=True,
        index=True
    )

    name = Column(
        String,
        nullable=False
    )

    code = Column(String, unique=True, index=True, nullable=True)
    district = Column(String, nullable=True)
    state = Column(String, nullable=True)
    address = Column(Text, nullable=True)
    contact_number = Column(String, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)

    location = Column(
        String
    )

    assigned_hospital_id = Column(
        Integer,
        ForeignKey("hospitals.id")
    )

    hospital = relationship(
        "Hospital",
        back_populates="health_centres"
    )

    patients = relationship(
        "Patient",
        back_populates="health_centre"
    )

    appointments = relationship(
        "Appointment",
        back_populates="health_centre"
    )

    notifications = relationship(
        "Notification",
        back_populates="health_centre"
    )

    screenings = relationship("Screening", back_populates="health_centre")


# ============================================================
# PATIENT
# ============================================================

class Patient(Base):
    __tablename__ = "patients"

    id = Column(
        Integer,
        primary_key=True,
        index=True
    )

    patient_code = Column(
        String,
        unique=True,
        index=True,
        nullable=False
    )

    name = Column(
        String,
        nullable=False
    )

    age = Column(
        Integer
    )

    sex = Column(
        String
    )

    phone = Column(String, nullable=True)

    health_centre_id = Column(
        Integer,
        ForeignKey("health_centres.id")
    )

    created_at = Column(
        DateTime,
        default=datetime.utcnow
    )

    health_centre = relationship(
        "HealthCentre",
        back_populates="patients"
    )

    screenings = relationship(
        "Screening",
        back_populates="patient"
    )

    appointments = relationship(
        "Appointment",
        back_populates="patient"
    )

    notifications = relationship(
        "Notification",
        back_populates="patient"
    )


# ============================================================
# SCREENING
# ============================================================

class Screening(Base):
    __tablename__ = "screenings"

    id = Column(
        Integer,
        primary_key=True,
        index=True
    )

    patient_id = Column(
        Integer,
        ForeignKey("patients.id"),
        nullable=False
    )

    health_centre_id = Column(
        Integer,
        ForeignKey("health_centres.id")
    )

    routed_hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=True, index=True)
    review_status = Column(String, nullable=False, default="PENDING")
    clinical_review_notes = Column(Text, nullable=True)
    clinical_outcome = Column(String, nullable=True)
    follow_up_required = Column(Boolean, nullable=True)
    clinical_reviewer_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    clinical_reviewed_at = Column(DateTime, nullable=True)
    clinically_flagged = Column(Boolean, nullable=False, default=False)
    follow_up_priority = Column(String, nullable=True)
    clinical_disposition = Column(String, nullable=True)
    disposition_recorded_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    disposition_updated_at = Column(DateTime, nullable=True)
    routed_at = Column(DateTime, nullable=True)
    submitted_at = Column(DateTime, nullable=True, index=True)
    hospital_attended_at = Column(DateTime, nullable=True)
    hospital_attended_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    original_report_pdf_path = Column(String, nullable=True)
    original_heatmap_path = Column(String, nullable=True)

    retinal_image_path = Column(
        String
    )

    prediction = Column(
        String
    )

    confidence = Column(
        String
    )

    probabilities = Column(
        Text
    )

    gradcam_image_path = Column(
        String
    )

    status = Column(
        String,
        default="SCREENED"
    )

    submitted_to_hospital = Column(
        String,
        default="NO"
    )

    # ========================================================
    # HOSPITAL CONSULTATION
    # ========================================================

    consulted_doctor = Column(
        String,
        nullable=True
    )

    doctor_notes = Column(
        Text,
        nullable=True
    )

    created_at = Column(
        DateTime,
        default=datetime.utcnow
    )

    patient = relationship(
        "Patient",
        back_populates="screenings"
    )

    health_centre = relationship("HealthCentre", back_populates="screenings")

    appointments = relationship(
        "Appointment",
        back_populates="screening"
    )


# ============================================================
# APPOINTMENT
# ============================================================

class Appointment(Base):
    __tablename__ = "appointments"

    id = Column(
        Integer,
        primary_key=True,
        index=True
    )

    # --------------------------------------------------------
    # Related screening
    # --------------------------------------------------------

    screening_id = Column(
        Integer,
        ForeignKey("screenings.id"),
        nullable=True
    )

    # --------------------------------------------------------
    # Patient
    # --------------------------------------------------------

    patient_id = Column(
        Integer,
        ForeignKey("patients.id"),
        nullable=False
    )

    # --------------------------------------------------------
    # Hospital
    # --------------------------------------------------------

    hospital_id = Column(
        Integer,
        ForeignKey("hospitals.id"),
        nullable=False
    )

    # --------------------------------------------------------
    # Assigned Health Centre
    # --------------------------------------------------------

    health_centre_id = Column(
        Integer,
        ForeignKey("health_centres.id"),
        nullable=False
    )

    # --------------------------------------------------------
    # Doctor
    # --------------------------------------------------------

    doctor_name = Column(
        String,
        nullable=False
    )

    # --------------------------------------------------------
    # Appointment date and time
    # --------------------------------------------------------

    appointment_datetime = Column(
        DateTime,
        nullable=False
    )

    appointment_end_datetime = Column(DateTime, nullable=True)

    missed_detected_at = Column(DateTime, nullable=True)

    # --------------------------------------------------------
    # Appointment type
    # --------------------------------------------------------

    appointment_type = Column(
        String,
        default="Hospital Consultation"
    )

    # --------------------------------------------------------
    # Appointment status
    #
    # SCHEDULED
    # ATTENDED
    # MISSED
    # CANCELLED
    # --------------------------------------------------------

    status = Column(
        String,
        default="SCHEDULED"
    )

    # --------------------------------------------------------
    # Additional notes
    # --------------------------------------------------------

    notes = Column(
        Text,
        nullable=True
    )

    # --------------------------------------------------------
    # Timestamps
    # --------------------------------------------------------

    created_at = Column(
        DateTime,
        default=datetime.utcnow
    )

    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )

    # ========================================================
    # RELATIONSHIPS
    # ========================================================

    screening = relationship(
        "Screening",
        back_populates="appointments"
    )

    patient = relationship(
        "Patient",
        back_populates="appointments"
    )

    hospital = relationship(
        "Hospital",
        back_populates="appointments"
    )

    health_centre = relationship(
        "HealthCentre",
        back_populates="appointments"
    )

    notifications = relationship(
        "Notification",
        back_populates="appointment"
    )


# ============================================================
# NOTIFICATION
# ============================================================

class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (UniqueConstraint("appointment_id", "notification_type", name="uq_notification_appointment_type"),)

    id = Column(
        Integer,
        primary_key=True,
        index=True
    )

    # --------------------------------------------------------
    # Health Centre receiving notification
    # --------------------------------------------------------

    health_centre_id = Column(
        Integer,
        ForeignKey("health_centres.id"),
        nullable=False
    )

    # --------------------------------------------------------
    # Patient related to notification
    # --------------------------------------------------------

    patient_id = Column(
        Integer,
        ForeignKey("patients.id"),
        nullable=False
    )

    # --------------------------------------------------------
    # Appointment related to notification
    # --------------------------------------------------------

    appointment_id = Column(
        Integer,
        ForeignKey("appointments.id"),
        nullable=True
    )

    # --------------------------------------------------------
    # Notification type
    # --------------------------------------------------------

    notification_type = Column(
        String,
        nullable=False
    )

    # --------------------------------------------------------
    # Notification message
    # --------------------------------------------------------

    message = Column(
        Text,
        nullable=False
    )

    # --------------------------------------------------------
    # Read/unread status
    # --------------------------------------------------------

    is_read = Column(
        Boolean,
        default=False
    )

    acknowledged_at = Column(DateTime, nullable=True)

    patient_phone = Column(String, nullable=True)
    appointment_time = Column(String, nullable=True)
    assigned_hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=True, index=True)
    referral_screening_id = Column(Integer, ForeignKey("screenings.id"), nullable=True, index=True)
    hospital_follow_up = Column(Text, nullable=True)
    hospital_follow_up_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    hospital_follow_up_at = Column(DateTime, nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    resolved_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    # --------------------------------------------------------
    # Created timestamp
    # --------------------------------------------------------

    created_at = Column(
        DateTime,
        default=datetime.utcnow
    )

    # ========================================================
    # RELATIONSHIPS
    # ========================================================

    health_centre = relationship(
        "HealthCentre",
        back_populates="notifications"
    )

    patient = relationship(
        "Patient",
        back_populates="notifications"
    )

    appointment = relationship(
        "Appointment",
        back_populates="notifications"
    )


class NetworkAudit(Base):
    __tablename__ = "network_audits"
    id = Column(Integer, primary_key=True)
    actor_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    health_centre_id = Column(Integer, ForeignKey("health_centres.id"), nullable=True)
    old_hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=True)
    new_hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=True)
    action = Column(String, nullable=False)
    details = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


