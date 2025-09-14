# app/utils/auth.py
import hmac
from flask import current_app
from app import db
from werkzeug.security import check_password_hash
from passlib.hash import bcrypt  # ← DŮLEŽITÉ: ověřujeme nejdřív přes passlib

def verify_and_upgrade_project_passphrase(project, candidate: str) -> bool:
    """
    Vrátí True, pokud heslo sedí.
    Pořadí pokusů:
      1) passlib bcrypt (aktuální)
      2) werkzeug (pbkdf2 apod., pokud by bylo historicky uloženo jinak)
      3) legacy plaintext (hmac.compare_digest) + auto-upgrade na bcrypt
    """
    stored = project.passphrase_hash or ""
    if not stored:
        return True  # projekt není zamčený

    # 1) passlib bcrypt
    try:
        if bcrypt.verify(candidate, stored):
            return True
    except Exception:
        pass

    # 2) werkzeug (pbkdf2:sha256:..., scrypt:..., atd.)
    try:
        if check_password_hash(stored, candidate):
            return True
    except Exception:
        pass

    # 3) fallback: plaintext (a hned přehashovat na bcrypt)
    try:
        if hmac.compare_digest(stored.encode("utf-8"), candidate.encode("utf-8")):
            project.set_passphrase(candidate)
            try:
                db.session.commit()
            except Exception as e:
                current_app.logger.warning(f"Passphrase upgrade failed: {e}")
                db.session.rollback()
            return True
    except Exception:
        pass

    return False
