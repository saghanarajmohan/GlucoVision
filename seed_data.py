from backend.database import SessionLocal
from backend.models import Hospital, HealthCentre


db = SessionLocal()

try:
    # Create demo hospital
    hospital = db.query(Hospital).filter(
        Hospital.name == "GlucoVision Main Hospital"
    ).first()

    if not hospital:
        hospital = Hospital(
            name="GlucoVision Main Hospital",
            location="Thanjavur, Tamil Nadu"
        )

        db.add(hospital)
        db.commit()
        db.refresh(hospital)

        print("Hospital created.")
    else:
        print("Hospital already exists.")

    # Create demo health centre
    health_centre = db.query(HealthCentre).filter(
        HealthCentre.name == "GlucoVision Rural Health Centre"
    ).first()

    if not health_centre:
        health_centre = HealthCentre(
            name="GlucoVision Rural Health Centre",
            location="Thanjavur, Tamil Nadu",
            assigned_hospital_id=hospital.id
        )

        db.add(health_centre)
        db.commit()

        print("Health centre created.")
    else:
        print("Health centre already exists.")

finally:
    db.close()