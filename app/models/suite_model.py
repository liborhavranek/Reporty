from __future__ import annotations

import re
from datetime import datetime

from sqlalchemy import UniqueConstraint
from sqlalchemy.orm import relationship
from app import db

def _slugify(name: str) -> str:
    s = re.sub(r'[^a-zA-Z0-9]+', '-', (name or '').strip()).strip('-').lower()
    return s or "suite"

class Suite(db.Model):
    """
    Jeden model pro obě úrovně:
      - sekce:   parent_id IS NULL
      - sekvence parent_id NOT NULL (odkazuje na sekci)
    """
    __tablename__ = "suites"

    id         = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    parent_id  = db.Column(db.Integer, db.ForeignKey("suites.id", ondelete="CASCADE"), nullable=True, index=True)

    name        = db.Column(db.String(160), nullable=False)
    slug        = db.Column(db.String(180), nullable=False)
    description = db.Column(db.Text, nullable=True)

    order_index = db.Column(db.Integer, nullable=False, default=0)
    is_active   = db.Column(db.Boolean, nullable=False, default=True)

    created_at  = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at  = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        # ve stejném projektu + stejném parentu musí být slug unikátní
        UniqueConstraint("project_id", "parent_id", "slug", name="uq_suite_slug_per_parent"),
    )

    # vztahy
    project  = relationship("Project", back_populates="suites")
    parent   = relationship("Suite", remote_side=[id], back_populates="children")
    children = relationship("Suite", back_populates="parent", cascade="all, delete-orphan")
    runs = db.relationship("Run", back_populates="suite", cascade="all, delete-orphan",
                           order_by="Run.created_at.desc()")

    @property
    def is_section(self) -> bool:
        return self.parent_id is None

    @property
    def is_sequence(self) -> bool:
        return self.parent_id is not None

    def ensure_unique_slug(self):
        base = _slugify(self.name)
        slug = base
        i = 2

        q = Suite.query.filter_by(project_id=self.project_id, parent_id=self.parent_id, slug=slug)
        if self.id:
            q = q.filter(Suite.id != self.id)

        while q.first():
            slug = f"{base}-{i}"
            i += 1
            q = Suite.query.filter_by(project_id=self.project_id, parent_id=self.parent_id, slug=slug)
            if self.id:
                q = q.filter(Suite.id != self.id)

        self.slug = slug