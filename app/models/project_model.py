import os
from datetime import datetime
import enum
import re
from typing import Optional
from flask import current_app
from sqlalchemy import func, UniqueConstraint, Index
from slugify import slugify
from passlib.hash import bcrypt

from app import db

# --- ENUMy, které fungují i na SQLite (native_enum=False) ---
class ProjectType(enum.Enum):
    web = "web"
    e2e = "e2e"

class Visibility(enum.Enum):
    private = "private"
    link_only = "link-only"
    public = "public"

class Project(db.Model):
    __tablename__ = "projects"

    id = db.Column(db.Integer, primary_key=True)

    # základ
    name = db.Column(db.String(120), nullable=False, unique=True)
    slug = db.Column(db.String(140), nullable=False, unique=True, index=True)

    type = db.Column(
        db.Enum(ProjectType, name="project_type", native_enum=False, validate_strings=True),
        nullable=False,
    )

    description = db.Column(db.Text, nullable=True)

    visibility = db.Column(
        db.Enum(Visibility, name="visibility", native_enum=False, validate_strings=True),
        nullable=False,
        default=Visibility.private,
        server_default="private",
    )

    # volitelné projektové heslo (hash)
    passphrase_hash = db.Column(db.String(255), nullable=True)

    # logo – ukládáme relativní cestu (např. "storage/logos/myproj.png")
    logo_path = db.Column(db.String(255), nullable=True)

    # audit
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    suites = db.relationship("Suite", back_populates="project", cascade="all, delete-orphan")
    runs = db.relationship("Run", back_populates="project", cascade="all, delete-orphan")
    pdfs = db.relationship("PdfReport", back_populates="project", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("name", name="uq_project_name"),
        Index("ix_projects_created_at", created_at.desc()),
    )

    # ---- helpers ----
    def set_passphrase(self, plaintext: Optional[str]) -> None:
        """Nastaví hash projektového hesla (nebo vymaže, pokud None/empty)."""
        if plaintext:
            self.passphrase_hash = bcrypt.hash(plaintext)
        else:
            self.passphrase_hash = None

    def verify_passphrase(self, plaintext: str) -> bool:
        if not self.passphrase_hash:
            return False
        try:
            return bcrypt.verify(plaintext, self.passphrase_hash)
        except Exception:
            return False

    @staticmethod
    def make_slug(name: str) -> str:
        # robustní a čitelné (řeší diakritiku přes python-slugify)
        base = slugify(name, lowercase=True, max_length=120)
        # fallback kdyby bylo prázdné
        return base or "project"

    def ensure_unique_slug(self):
        base = self.slug or self.make_slug(self.name)
        slug = base
        n = 2
        while Project.query.filter(Project.slug == slug, Project.id != (self.id or 0)).first():
            slug = f"{base}-{n}"
            n += 1
        self.slug = slug

    @property
    def logo_abspath(self) -> Optional[str]:
        if not self.logo_path:
            return None
        # pokud je uložená relativní cesta, doplníme absolutní
        if self.logo_path.startswith(("storage/", "uploads/")):
            return f"{self.logo_path}"
        return f"{current_app.config.get('UPLOAD_DIR','storage/logos').rstrip('/')}/{self.logo_path}"

    def __repr__(self) -> str:
        return f"<Project {self.id} {self.slug} ({self.type.value})>"