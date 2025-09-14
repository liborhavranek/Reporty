# app/models/run_model.py
from datetime import datetime
from sqlalchemy.orm import relationship
from app import db

class Run(db.Model):
    __tablename__ = "runs"

    id         = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    suite_id   = db.Column(db.Integer, db.ForeignKey("suites.id", ondelete="CASCADE"),   nullable=False, index=True)

    # volitelné krátké jméno; když ho nevyplníš, zobrazíme název souboru
    label      = db.Column(db.String(200), nullable=True)

    # relativní cesta v REPORTS_DIR, např.: "my-proj/sekvence/2025-09-13_170805-report.csv"
    csv_path   = db.Column(db.String(500), nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # relace
    project = relationship("Project", back_populates="runs")
    suite   = relationship("Suite",   back_populates="runs")