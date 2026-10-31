"""Explicit, backup-first reset of GlucoVision demonstration records.

Run manually from the project root. This never removes the SQLite file, schema,
models, uploaded AI weights, or application configuration.
"""
from datetime import datetime
from getpass import getpass
from pathlib import Path
import sqlite3

from backend import main as _schema_migrations  # noqa: F401 - applies additive migrations
from backend.database import engine, SessionLocal
from backend.models import User
from backend.auth import hash_password


ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "glucovision.db"
BACKUP_DIR = ROOT / "database_backups"


def main():
    if not DB_PATH.exists():
        raise SystemExit(f"Database not found: {DB_PATH}")
    BACKUP_DIR.mkdir(exist_ok=True)
    backup_path = BACKUP_DIR / f"glucovision-pre-reset-{datetime.now().strftime('%Y%m%d-%H%M%S')}.db"
    source = sqlite3.connect(str(DB_PATH))
    destination = sqlite3.connect(str(backup_path))
    try:
        source.backup(destination)
        check = destination.execute("PRAGMA integrity_check").fetchone()[0]
        if check != "ok":
            raise RuntimeError(f"Backup integrity check failed: {check}")
    finally:
        destination.close()
        source.close()
    print(f"Verified backup created: {backup_path}")
    if input("Type RESET to remove demonstration records: ").strip() != "RESET":
        raise SystemExit("Reset cancelled; the verified backup was retained.")

    admin_db = SessionLocal()
    try:
        has_admin = admin_db.query(User).filter(User.role.ilike("SUPER_ADMIN")).first() is not None
    finally:
        admin_db.close()
    new_admin = None
    if not has_admin:
        username = input("Create first super-admin username: ").strip()
        password = getpass("Create super-admin password: ")
        confirmation = getpass("Confirm password: ")
        if not username or len(password) < 12 or password != confirmation:
            raise SystemExit("A username is required; passwords must match and contain at least 12 characters. Backup was retained; data was not reset.")
        new_admin = (username, hash_password(password))

    connection = sqlite3.connect(str(DB_PATH))
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("BEGIN IMMEDIATE")
        for table in ("network_audits", "notifications", "appointments", "screenings", "patients"):
            connection.execute(f'DELETE FROM "{table}"')
        # Keep only the super-admin account(s); other demo logins are discarded.
        connection.execute("DELETE FROM users WHERE upper(role) != 'SUPER_ADMIN'")
        connection.execute("UPDATE users SET hospital_id=NULL, health_centre_id=NULL")
        connection.execute("DELETE FROM health_centres")
        connection.execute("DELETE FROM hospitals")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    db = SessionLocal()
    try:
        if new_admin:
            db.add(User(name="Super Administrator", username=new_admin[0], password_hash=new_admin[1], role="SUPER_ADMIN"))
            db.commit()
    finally:
        db.close()
    print("Reset complete. Schema and application files were preserved.")


if __name__ == "__main__":
    main()
