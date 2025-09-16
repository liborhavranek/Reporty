from __future__ import annotations
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, current_app, \
    send_from_directory
from app.forms.project_form import ProjectCreateForm
from werkzeug.security import check_password_hash, safe_join
from app.models.project_model import Project
from werkzeug.utils import secure_filename
from app.models.run_model import Run
from app.models.suite_model import Suite
from app.forms.suite_form import SuiteForm
from app import db, csrf
from uuid import uuid4
import os
from sqlalchemy import func
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.utils.csv_report import parse_report_csv

admin_bp = Blueprint("admin", __name__, template_folder="templates")

ALLOWED = {"csv"}

def _allowed_csv(name: str) -> bool:
    return "." in name and name.rsplit(".", 1)[1].lower() in ALLOWED

# --------- Ochrana: vše pod /admin kromě /login vyžaduje přihlášení ----------
@admin_bp.before_request
def _require_admin():
    allowed = {"admin.login"}
    if request.endpoint in allowed:
        return
    if not session.get("is_admin"):
        return redirect(url_for("admin.login", next=request.path))

# --------- Login / Logout ----------
@admin_bp.route("/login", methods=["GET", "POST"])
def login():
    # Když už je přihlášen, rovnou na admin list
    if session.get("is_admin"):
        return redirect(url_for("admin.projects"))

    if request.method == "POST":
        pwd   = request.form.get("password", "")
        hash_ = current_app.config.get("ADMIN_PASS_HASH")
        plain = current_app.config.get("ADMIN_PASSWORD")

        ok = False
        if hash_:
            ok = check_password_hash(hash_, pwd)
        elif plain is not None:
            ok = (pwd == plain)

        if ok:
            session["is_admin"] = True
            flash("Přihlášení OK.", "success")
            # 🔒 Ignorujeme `next` a JEDNOZNAČNĚ posíláme na /admin/projects
            return redirect(url_for("admin.projects"))

        flash("Špatné heslo.", "error")

    return render_template("admin/login.html")

@admin_bp.get("/logout")
@csrf.exempt  # pokud podáváš jen POST bez formuláře WTForms; když WTForms, můžeš CSRF nechat
def logout():
    session.clear()
    flash("Odhlášeno.", "success")
    return redirect(url_for("bp.public_projects_list"))  # uprav na svůj veřejný endpoint

# --------- Admin: seznam projektů (s akcemi) ----------
@admin_bp.get("/projects")
def projects():
    q = (request.args.get('q') or '').strip()

    query = Project.query
    if q:
        like = f"%{q}%"
        query = query.filter(Project.name.ilike(like))  # jen podle názvu
    projects = query.order_by(Project.created_at.desc()).all()
    return render_template("admin/projects_list.html", projects=projects, q=q)

# --------- Vytvořit projekt ----------
@admin_bp.route("/projects/new", methods=["GET", "POST"])
def projects_new():
    form = ProjectCreateForm()
    if form.validate_on_submit():
        p = Project(
            name=form.name.data.strip(),
            type=form.type.data,
            visibility=form.visibility.data,
            description=(form.description.data or None),
        )

        # heslo pouze pokud je vyplněné (hash!)
        new_pass = (form.passphrase.data or "").strip()
        if new_pass:
            p.set_passphrase(new_pass)   # -> generate_password_hash uvnitř

        # logo (volitelné) – beze změny
        file = request.files.get("logo")
        if file and file.filename:
            ext = file.filename.rsplit(".", 1)[-1].lower()
            if ext in {"png","jpg","jpeg","webp","svg"}:
                fname = f"{uuid4().hex}.{ext}"
                path = os.path.join(current_app.config["UPLOAD_DIR"], secure_filename(fname))
                os.makedirs(os.path.dirname(path), exist_ok=True)
                file.save(path)
                p.logo_path = fname

        p.ensure_unique_slug()
        db.session.add(p)
        db.session.commit()
        flash("Projekt vytvořen.", "success")
        return redirect(url_for("admin.projects"))

    return render_template("admin/project_new.html", form=form)

# --------- Editovat projekt ----------
@admin_bp.route("/projects/<int:project_id>/edit", methods=["GET", "POST"])
def projects_edit(project_id: int):
    p = Project.query.get_or_404(project_id)
    form = ProjectCreateForm(obj=p)

    if form.validate_on_submit():
        p.name        = form.name.data.strip()
        p.type        = form.type.data
        p.visibility  = form.visibility.data
        p.description = (form.description.data or None)

        # --- heslo ---
        clear = bool(request.form.get("clear_passphrase"))
        new_pass = (form.passphrase.data or "").strip()

        if clear:
            p.passphrase_hash = None              # smazat heslo
        elif new_pass:
            p.set_passphrase(new_pass)            # nastavit nové (hash)
        # jinak ponechat stávající hash beze změny

        # --- logo (volitelné) ---
        file = request.files.get("logo")
        if file and file.filename:
            ext = file.filename.rsplit(".", 1)[-1].lower()
            if ext in {"png","jpg","jpeg","webp","svg"}:
                fname = f"{uuid4().hex}.{ext}"
                path = os.path.join(current_app.config["UPLOAD_DIR"], secure_filename(fname))
                os.makedirs(os.path.dirname(path), exist_ok=True)
                file.save(path)
                if p.logo_path:
                    try:
                        os.remove(os.path.join(current_app.config["UPLOAD_DIR"], os.path.basename(p.logo_path)))
                    except OSError:
                        pass
                p.logo_path = fname

        p.ensure_unique_slug()
        db.session.commit()
        flash("Projekt upraven.", "success")
        return redirect(url_for("admin.projects"))

    return render_template("admin/projects_edit.html", form=form, project=p)


# --------- Smazat projekt ----------
@admin_bp.post("/projects/<int:project_id>/delete")
def projects_delete(project_id: int):
    p = Project.query.get_or_404(project_id)
    if p.logo_path:
        try:
            os.remove(os.path.join(current_app.config["UPLOAD_DIR"], os.path.basename(p.logo_path)))
        except OSError:
            pass
    db.session.delete(p)
    db.session.commit()
    flash("Projekt smazán.", "success")
    return redirect(url_for("admin.projects"))

######################### SUITES ROUTES #########################################

@admin_bp.get("/projects/<int:project_id>")
def project_detail_admin(project_id: int):
    # čistý redirect na /admin/projects/<id>/suites (správa stromu)
    return redirect(url_for("admin.suites", project_id=project_id))

# --- List sad pro projekt (karty) ---
@admin_bp.get("/projects/<int:project_id>/suites")
def suites(project_id: int):
    project = Project.query.get_or_404(project_id)

    sections = (Suite.query
                .filter_by(project_id=project.id, parent_id=None)
                .order_by(Suite.order_index.asc(), Suite.name.asc())
                .all())

    # poslední nahrání per suite (beze změny)
    last_by_suite = dict(
        db.session.query(Run.suite_id, func.max(Run.created_at))
        .filter(Run.project_id == project.id)
        .group_by(Run.suite_id)
        .all()
    )

    # --- DNEŠEK: interval 00:00–24:00 v CZ čase ---
    tz = ZoneInfo("Europe/Prague")
    now = datetime.now(tz)
    day_start_local = now.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end_local   = day_start_local + timedelta(days=1)

    # Pokud máš Run.created_at v UTC (typicky ano), převeď hranice do UTC:
    day_start = day_start_local.astimezone(ZoneInfo("UTC"))
    day_end   = day_end_local.astimezone(ZoneInfo("UTC"))

    # Počty dnešních nahrávek po jednotlivých sekvencích (suite_id)
    rows = (db.session.query(Run.suite_id, func.count(Run.id))
            .filter(
                Run.project_id == project.id,
                Run.created_at >= day_start,
                Run.created_at <  day_end
            )
            .group_by(Run.suite_id)
            .all())

    today_counts_by_suite = {suite_id: cnt for suite_id, cnt in rows}
    today_total = sum(today_counts_by_suite.values())

    return render_template(
        "admin/suites_list.html",
        project=project,
        sections=sections,
        last_by_suite=last_by_suite,
        today_counts_by_suite=today_counts_by_suite,  # 👈 per-sekvence pro šablonu
        today_total=today_total                       # 👈 součet (volitelné KPI nahoře)
    )
# --- Vytvořit sadu (sekci/sekvenci) ---
@admin_bp.route("/projects/<int:project_id>/suites/new", methods=["GET", "POST"])
def suites_new(project_id: int):
    project = Project.query.get_or_404(project_id)
    form = SuiteForm()

    # naplnění parent choices (jen sekce)
    top_sections = (Suite.query
                    .filter_by(project_id=project.id, parent_id=None)
                    .order_by(Suite.order_index.asc(), Suite.name.asc())
                    .all())
    form.parent_id.choices = [(0, "— žádná (SEKCE)")] + [(s.id, f"Sekce: {s.name}") for s in top_sections]

    # předvyplnění parent z query parametru
    q_parent = request.args.get("parent_id", type=int)
    if request.method == "GET" and q_parent:
        form.parent_id.data = q_parent

    if form.validate_on_submit():
        parent_id = form.parent_id.data or None
        # pravidlo hloubky: pokud parent_id != None, parent musí být top-level (tj. parent.parent_id is None)
        if parent_id:
            parent = Suite.query.filter_by(project_id=project.id, id=parent_id).first()
            if not parent or parent.parent_id is not None:
                flash("Neplatný parent (povolena je pouze hloubka 1).", "error")
                return render_template("admin/suite_new.html", project=project, form=form)

        s = Suite(
            project_id=project.id,
            parent_id=parent_id,
            name=form.name.data.strip(),
            description=form.description.data.strip() if form.description.data else None,
            order_index=form.order_index.data or 0,
            is_active=bool(form.is_active.data),
        )
        s.ensure_unique_slug()
        db.session.add(s)
        db.session.commit()
        flash("Sada vytvořena.", "success")
        return redirect(url_for("admin.suites", project_id=project.id))

    return render_template("admin/suite_new.html", project=project, form=form)

# --- Editace sady ---
@admin_bp.route("/projects/<int:project_id>/suites/<int:suite_id>/edit", methods=["GET", "POST"])
def suites_edit(project_id: int, suite_id: int):
    project = Project.query.get_or_404(project_id)
    s = Suite.query.filter_by(project_id=project.id, id=suite_id).first_or_404()

    form = SuiteForm(obj=s)
    top_sections = (Suite.query
                    .filter_by(project_id=project.id, parent_id=None)
                    .order_by(Suite.order_index.asc(), Suite.name.asc())
                    .all())
    form.parent_id.choices = [(0, "— žádná (SEKCE)")] + [(x.id, f"Sekce: {x.name}") for x in top_sections if x.id != s.id]

    if request.method == "GET":
        form.parent_id.data = s.parent_id or 0

    if form.validate_on_submit():
        parent_id = form.parent_id.data or None
        if parent_id:
            parent = Suite.query.filter_by(project_id=project.id, id=parent_id).first()
            if not parent or parent.parent_id is not None:
                flash("Neplatný parent (povolena je pouze hloubka 1).", "error")
                return render_template("admin/suite_edit.html", project=project, form=form, suite=s)

        s.name        = form.name.data.strip()
        s.description = form.description.data.strip() if form.description.data else None
        s.order_index = form.order_index.data or 0
        s.is_active   = bool(form.is_active.data)
        s.parent_id   = parent_id
        s.ensure_unique_slug()
        db.session.commit()
        flash("Uloženo.", "success")
        return redirect(url_for("admin.suites", project_id=project.id))

    return render_template("admin/suite_edit.html", project=project, form=form, suite=s)

# --- Smazání sady ---
@admin_bp.post("/projects/<int:project_id>/suites/<int:suite_id>/delete")
def suites_delete(project_id: int, suite_id: int):
    project = Project.query.get_or_404(project_id)
    s = Suite.query.filter_by(project_id=project.id, id=suite_id).first_or_404()
    db.session.delete(s)
    db.session.commit()
    flash("Sada smazána.", "success")
    return redirect(url_for("admin.suites", project_id=project.id))


######################### RUN ROUTES #########################################

@admin_bp.route("/storage/reports/<path:filename>")
def storage_reports(filename):
    return send_from_directory(current_app.config["REPORTS_DIR"], filename, conditional=True)

@admin_bp.get("/projects/<int:project_id>/suites/<int:suite_id>/runs")
def runs_list(project_id: int, suite_id: int):
    if not session.get("is_admin"):
        return redirect(url_for("admin.login", next=request.path))

    project = Project.query.get_or_404(project_id)
    suite   = Suite.query.filter_by(id=suite_id, project_id=project_id).first_or_404()
    runs    = (Run.query
                  .filter_by(project_id=project.id, suite_id=suite.id)
                  .order_by(Run.created_at.desc())
                  .all())

    # doplň stats pro každý běh (bez dalších DB změn; čte přímo CSV)
    base_dir = current_app.config["REPORTS_DIR"]
    for r in runs:
        r.stats = None
        try:
            rel = (r.csv_path or "").lstrip("/\\")
            abs_path = safe_join(base_dir, rel)
            if abs_path and os.path.isfile(abs_path):
                rep = parse_report_csv(abs_path)
                r.stats = rep.get("summary") or {}
        except Exception:
            r.stats = None

    return render_template("admin/runs_list.html", project=project, suite=suite, runs=runs)

@admin_bp.post("/projects/<int:project_id>/suites/<int:suite_id>/runs")
def runs_upload(project_id: int, suite_id: int):
    if not session.get("is_admin"):
        return redirect(url_for("admin.login", next=request.path))

    project = Project.query.get_or_404(project_id)
    suite   = Suite.query.filter_by(id=suite_id, project_id=project_id).first_or_404()

    f = request.files.get("csv")
    label = (request.form.get("label") or "").strip()

    if not f or not f.filename:
        flash("Vyber CSV soubor.", "error")
        return redirect(url_for("admin.runs_list", project_id=project.id, suite_id=suite.id))
    if not _allowed_csv(f.filename):
        flash("Povolené jsou jen .csv soubory.", "error")
        return redirect(url_for("admin.runs_list", project_id=project.id, suite_id=suite.id))

    ts = datetime.utcnow().strftime("%Y-%m-%d_%H%M%S")
    safe = secure_filename(f.filename) or "report.csv"
    # ukládáme do REPORTS_DIR/<project>/<suite>/<timestamp>-<file>
    rel_dir  = f"{project.slug}/{suite.slug}"
    abs_dir  = os.path.join(current_app.config["REPORTS_DIR"], rel_dir)
    os.makedirs(abs_dir, exist_ok=True)

    rel_path = f"{rel_dir}/{ts}-{safe}"
    abs_path = os.path.join(current_app.config["REPORTS_DIR"], rel_path)
    f.save(abs_path)

    run = Run(project_id=project.id, suite_id=suite.id,
              label=label or os.path.splitext(safe)[0],
              csv_path=rel_path)
    db.session.add(run)
    db.session.commit()

    flash("CSV nahráno.", "success")
    return redirect(url_for("admin.runs_list", project_id=project.id, suite_id=suite.id))

@admin_bp.post("/projects/<int:project_id>/suites/<int:suite_id>/runs/<int:run_id>/delete")
def runs_delete(project_id: int, suite_id: int, run_id: int):
    if not session.get("is_admin"):
        return redirect(url_for("admin.login", next=request.path))

    run = Run.query.filter_by(id=run_id, project_id=project_id, suite_id=suite_id).first_or_404()

    # smaž soubor, pokud existuje
    try:
        os.remove(os.path.join(current_app.config["REPORTS_DIR"], run.csv_path))
    except OSError:
        pass

    db.session.delete(run)
    db.session.commit()
    flash("Běh smazán.", "success")
    return redirect(url_for("admin.runs_list", project_id=project_id, suite_id=suite_id))