from sqlalchemy import func, Index
from app import db

class PdfReport(db.Model):
    __tablename__ = "pdf_reports"

    id         = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    suite_id   = db.Column(db.Integer, db.ForeignKey("suites.id", ondelete="SET NULL"), nullable=True, index=True)

    label    = db.Column(db.String(200), nullable=False)
    pdf_path = db.Column(db.String(255), nullable=False, unique=True)
    size     = db.Column(db.Integer, nullable=True)

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, server_default=func.now())

    project = db.relationship("Project", back_populates="pdfs")
    suite   = db.relationship("Suite", backref="pdf_reports")

    __table_args__ = (Index("ix_pdf_reports_created_at", created_at.desc()),)