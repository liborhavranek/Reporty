# app/routes.py
import hmac
import os
from urllib.parse import urlparse

from flask import request, abort, session, redirect, url_for, flash
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import safe_join

from app import db
from app.models.run_model import Run
from app.utils.auth import verify_and_upgrade_project_passphrase
from app.utils.csv_report import parse_report_csv
from flask import Blueprint, render_template, send_from_directory, current_app
from app.models.project_model import Project
from app.models.suite_model import Suite
from app.models.pdf_model import PdfReport

bp = Blueprint("bp", __name__)

ALLOWED_LOGO_EXT = {"png", "jpg", "jpeg", "webp", "svg"}

def _ext_allowed(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_LOGO_EXT

@bp.route("/storage/logos/<path:filename>")
def storage_logos(filename):
    safe_name = os.path.basename(filename)
    return send_from_directory(
        current_app.config["UPLOAD_DIR"], safe_name, conditional=True
    )

def _safe_next(default):
    nxt = request.args.get("next") or default
    # odstraň trailing '?', který vzniká z request.full_path
    if nxt.endswith("?"):
        nxt = nxt[:-1]
    # povol jen interní URL
    url = urlparse(nxt)
    if url.netloc and url.netloc != request.host:
        return default
    return nxt

def _has_access(project):
    granted = session.get("proj_access", {})
    return bool(granted.get(str(project.id)))

def _require_or_redirect(project: Project):
    if getattr(project, "passphrase_hash", None) and not _has_access(project):
        return redirect(url_for("bp.project_access", slug=project.slug, next=request.full_path))
    return None

@bp.get("/storage/pdfs/<path:filename>")
def storage_pdfs(filename: str):
    safe = os.path.normpath(filename).lstrip("/\\")
    if safe.startswith(("..", "/", "\\")):
        abort(404)
    return send_from_directory(current_app.config["PDFS_DIR"], safe, conditional=True)

@bp.route("/")
def home():
    return render_template("index.html", title="Reporty")

@bp.get("/projects")
def public_projects_list():
    q = (request.args.get('q') or '').strip()

    query = Project.query
    if q:
        like = f"%{q}%"
        query = query.filter(Project.name.ilike(like))  # jen podle názvu

    projects = query.order_by(Project.created_at.desc()).all()
    return render_template("projects_list.html", projects=projects, q=q)

@bp.get("/projects/<int:project_id>/open")
def project_open(project_id: int):
    p = Project.query.get_or_404(project_id)
    if (hasattr(p.type, "value") and p.type.value == "web") or str(p.type) == "web":
        return redirect(url_for("bp.web_pdf_list", project_id=p.id), code=302)
    return redirect(url_for("bp.project_detail", slug=p.slug), code=302)


def _has_project_access(project) -> bool:
    if session.get("is_admin"):
        return True
    if not project.passphrase_hash:
        return True
    return bool(session.get("proj_access", {}).get(str(project.id)))

@bp.get("/projects/<slug>")
def project_detail(slug):
    p = Project.query.filter_by(slug=slug).first_or_404()
    gate = _require_or_redirect(p)
    if gate:
        return gate

    project = Project.query.filter_by(slug=slug).first_or_404()
    if not _has_project_access(project):
        return redirect(url_for("bp.project_access_form",
                                slug=slug,
                                next=url_for("bp.project_detail", slug=slug)))

    # načti všechny suite v projektu a rozděl je na sekce / sekvence
    suites = (Suite.query
              .filter_by(project_id=p.id)
              .order_by(Suite.order_index, Suite.name)
              .all())

    sections = [s for s in suites if s.parent_id is None and s.is_active]
    children_by_parent = {
        s.id: [c for c in suites if c.parent_id == s.id and c.is_active]
        for s in sections
    }

    return render_template(
        "suites_list.html",
        project=p,
        sections=sections,
        children=children_by_parent,
    )

@bp.get("/projects/<int:project_id>/suites/<int:suite_id>/runs")
def runs_list(project_id: int, suite_id: int):
    project = Project.query.get_or_404(project_id)

    gate = _require_or_redirect(project)
    if gate:
        return gate

    suite = Suite.query.filter_by(id=suite_id, project_id=project_id).first_or_404()
    # jen LEAF (sekvence), ne sekce:
    if suite.parent_id is None:
        abort(404)

    runs = (Run.query
              .filter_by(project_id=project_id, suite_id=suite_id)
              .order_by(Run.created_at.desc())
              .all())

    # pro každý běh spočti summary z CSV
    base = current_app.config["REPORTS_DIR"]
    for r in runs:
        r.stats = None
        rel = (r.csv_path or "").lstrip("/\\")
        abs_path = safe_join(base, rel)
        if abs_path and os.path.isfile(abs_path):
            try:
                rep = parse_report_csv(abs_path)
                s = rep.get("summary", {})
                r.stats = {
                    "total":        s.get("total"),
                    "passed":       s.get("passed"),
                    "failed":       s.get("failed"),
                    "skipped":      s.get("skipped"),
                    "duration_fmt": s.get("duration_fmt"),
                }
            except Exception as e:
                current_app.logger.warning("CSV parse failed for %s: %s", abs_path, e)
                r.stats = None

    return render_template(
        "runs_list.html",
        project=project,
        suite=suite,
        runs=runs,
    )

@bp.route("/storage/reports/<path:filename>")
def storage_reports(filename):
    safe = os.path.normpath(filename).lstrip("/\\")
    if safe.startswith(("..", "/", "\\")):
        abort(404)
    return send_from_directory(current_app.config["REPORTS_DIR"], safe, conditional=True)


@bp.get("/report")
def report_view():
    """
    /report?file=<relativni/cesta.csv>
    Soubor se hledá v REPORTS_DIR, cestu sanitizujeme proti path traversal.
    """
    rel = (request.args.get("file") or "").strip()
    if not rel:
        abort(400, description="Missing ?file")

    # vyčisti cestu
    rel = rel.lstrip("/\\")
    abs_path = safe_join(current_app.config["REPORTS_DIR"], rel)
    if not abs_path or not os.path.isfile(abs_path):
        abort(404)

    report = parse_report_csv(abs_path)
    # volitelně můžeš doplnit project/suite do breadcrumbs z rel path:
    # crumbs = rel.split("/")[:-1]
    return render_template("report_view.html", rel_path=rel, report=report)

@bp.route("/projects/<slug>/access", methods=["GET", "POST"])
def project_access(slug):
    project = Project.query.filter_by(slug=slug).first_or_404()
    next_url = _safe_next(url_for("bp.project_detail", slug=slug))

    if session.get("is_admin") or _has_access(project) or not project.passphrase_hash:
        return redirect(next_url)

    if request.method == "POST":
        pwd = (request.form.get("password") or "").strip()
        ok = verify_and_upgrade_project_passphrase(project, pwd)  # ← TADY

        if ok:
            granted = session.get("proj_access", {})
            granted[str(project.id)] = True
            session["proj_access"] = granted
            session.modified = True
            return redirect(next_url)

        flash("Špatné heslo.", "error")
        return redirect(url_for("bp.project_access", slug=slug, next=next_url))

    return render_template("project_access.html", project=project, next_url=next_url)

@bp.get("/projects/<int:project_id>/pdfs")
def web_pdf_list(project_id: int):
    project = Project.query.get_or_404(project_id)

    # gate: respektuj heslo/visibility stejně jako jinde
    gate = _require_or_redirect(project)
    if gate:
        return gate

    # jen pro WEB projekty
    if (hasattr(project.type, "value") and project.type.value != "web") and str(project.type) != "web":
        abort(404)

    pdfs = (PdfReport.query
            .filter_by(project_id=project.id)
            .order_by(PdfReport.created_at.desc())
            .all())

    return render_template("web_pdf_list.html", project=project, pdfs=pdfs)
