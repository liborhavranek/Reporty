from __future__ import annotations
from flask import (
    Blueprint, render_template, request, redirect, url_for, session,
    flash, current_app, send_from_directory
)
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
import shutil
from sqlalchemy import func
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.utils.csv_report import parse_report_csv

# =============================================================================
# ADMIN BLUEPRINT
# =============================================================================
admin_bp = Blueprint("admin", __name__, template_folder="templates")

ALLOWED = {"csv"}

def _allowed_csv(name: str) -> bool:
    return "." in name and name.rsplit(".", 1)[1].lower() in ALLOWED

# ---------- FS helpery (bezpečné mazání v REPORTS_DIR) ----------

def _reports_base() -> str:
    return current_app.config["REPORTS_DIR"]

def _rm_tree_safe(abs_path: str) -> None:
    """Smaže celý strom, jen pokud leží uvnitř REPORTS_DIR."""
    base = os.path.realpath(_reports_base())
    target = os.path.realpath(abs_path)
    if os.path.commonpath([base, target]) != base:
        return
    try:
        shutil.rmtree(target)
    except FileNotFoundError:
        pass
    except OSError:
        # nechceme blokovat transakci kvůli FS chybě
        pass

def _rm_file_safe(rel_path: str) -> None:
    """Smaže soubor podle relativní cesty v REPORTS_DIR."""
    if not rel_path:
        return
    base = _reports_base()
    abs_path = safe_join(base, rel_path.lstrip("/\\"))
    if not abs_path:
        return
    try:
        os.remove(abs_path)
    except FileNotFoundError:
        pass
    except OSError:
        pass

def _prune_empty_dirs(rel_path: str, stop_at: str | None = None) -> None:
    """
    Po smazání souboru/složky zkusí vyčistit prázdné nadřazené složky až po `stop_at`
    (relativně vůči REPORTS_DIR). V našem layoutu dává smysl stopnout na
    '<project_slug>' nebo '<project_slug>/<suite_slug>'.
    """
    base = _reports_base()
    cur = safe_join(base, rel_path.strip("/"))
    if not cur:
        return
    base_real = os.path.realpath(base)
    stop_abs = safe_join(base, (stop_at or "").strip("/")) if stop_at else base

    try:
        while True:
            if not cur or os.path.realpath(cur) in (base_real, os.path.realpath(stop_abs)):
                break
            try:
                os.rmdir(cur)  # smaže jen pokud je prázdná
            except OSError:
                break
            cur = os.path.dirname(cur)
    except Exception:
        pass

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
    # pokud už je admin nebo už je user přihlášený → rovnou na projekty
    if session.get("is_admin") or session.get("user_id"):
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
            return redirect(url_for("admin.projects"))

        flash("Špatné heslo.", "error")

    return render_template("admin/login.html")


@admin_bp.get("/logout")
@csrf.exempt
def logout():
    session.clear()
    flash("Odhlášeno.", "success")
    return redirect(url_for("bp.public_projects_list"))

# --------- Admin: seznam projektů ----------
@admin_bp.get("/projects")
def projects():
    q = (request.args.get('q') or '').strip()
    query = Project.query
    if q:
        like = f"%{q}%"
        query = query.filter(Project.name.ilike(like))
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
        new_pass = (form.passphrase.data or "").strip()
        if new_pass:
            p.set_passphrase(new_pass)

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

        clear = bool(request.form.get("clear_passphrase"))
        new_pass = (form.passphrase.data or "").strip()
        if clear:
            p.passphrase_hash = None
        elif new_pass:
            p.set_passphrase(new_pass)

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

# --------- Smazat projekt (včetně reportů na disku) ----------
@admin_bp.post("/projects/<int:project_id>/delete")
def projects_delete(project_id: int):
    p = Project.query.get_or_404(project_id)

    # 1) Logo
    if p.logo_path:
        try:
            os.remove(os.path.join(current_app.config["UPLOAD_DIR"], os.path.basename(p.logo_path)))
        except OSError:
            pass

    # 2) Smazání všech složek s reporty pro daný projekt:
    #    Nespoléháme jen na aktuální slug – projdeme běhy a sebereme top-level adresáře,
    #    protože slug se mohl v minulosti měnit.
    base = _reports_base()
    top_dirs = set()
    for run in p.runs:
        rel = (run.csv_path or "").lstrip("/\\")
        parts = rel.split("/", 1)
        if parts and parts[0]:
            top_dirs.add(parts[0])

    # Pokud nemáme žádné runy, smažeme adresář podle aktuálního slugu (pokud existuje)
    if not top_dirs and p.slug:
        top_dirs.add(p.slug)

    for top in top_dirs:
        abs_dir = safe_join(base, top)
        if abs_dir:
            _rm_tree_safe(abs_dir)

    # 3) DB delete (CASCADE smaže suites i runs)
    db.session.delete(p)
    db.session.commit()

    flash("Projekt smazán.", "success")
    return redirect(url_for("admin.projects"))

######################### SUITES ROUTES #########################################

@admin_bp.get("/projects/<int:project_id>")
def project_detail_admin(project_id: int):
    return redirect(url_for("admin.suites", project_id=project_id))

@admin_bp.get("/projects/<int:project_id>/suites")
def suites(project_id: int):
    project = Project.query.get_or_404(project_id)
    sections = (Suite.query
                .filter_by(project_id=project.id, parent_id=None)
                .order_by(Suite.order_index.asc(), Suite.name.asc())
                .all())

    last_by_suite = dict(
        db.session.query(Run.suite_id, func.max(Run.created_at))
        .filter(Run.project_id == project.id)
        .group_by(Run.suite_id)
        .all()
    )

    tz = ZoneInfo("Europe/Prague")
    now = datetime.now(tz)
    day_start_local = now.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end_local   = day_start_local + timedelta(days=1)
    day_start = day_start_local.astimezone(ZoneInfo("UTC"))
    day_end   = day_end_local.astimezone(ZoneInfo("UTC"))

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
        today_counts_by_suite=today_counts_by_suite,
        today_total=today_total
    )

# --- Vytvořit sadu ---
@admin_bp.route("/projects/<int:project_id>/suites/new", methods=["GET", "POST"])
def suites_new(project_id: int):
    project = Project.query.get_or_404(project_id)
    form = SuiteForm()

    top_sections = (Suite.query
                    .filter_by(project_id=project.id, parent_id=None)
                    .order_by(Suite.order_index.asc(), Suite.name.asc())
                    .all())
    form.parent_id.choices = [(0, "— žádná (SEKCE)")] + [(s.id, f"Sekce: {s.name}") for s in top_sections]

    q_parent = request.args.get("parent_id", type=int)
    if request.method == "GET" and q_parent:
        form.parent_id.data = q_parent

    if form.validate_on_submit():
        parent_id = form.parent_id.data or None
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

# --- Smazání sady (sekce NEBO sekvence) ---
@admin_bp.post("/projects/<int:project_id>/suites/<int:suite_id>/delete")
def suites_delete(project_id: int, suite_id: int):
    project = Project.query.get_or_404(project_id)
    s = Suite.query.filter_by(project_id=project.id, id=suite_id).first_or_404()

    base = _reports_base()

    # 1) Které sady mazat na disku: tahle + všechny její přímé děti (u tebe je hloubka max 1)
    suites_to_wipe = [s] + list(s.children)

    # 2) Nasbírej adresáře <project>/<suite> z běhů (ať pokryjeme i staré slugs), fallback na aktuální slug
    dirs = set()
    for su in suites_to_wipe:
        has_runs = False
        for run in su.runs:
            rel = (run.csv_path or "").lstrip("/\\")
            parts = rel.split("/", 2)  # očekáváme "<proj>/<suite>/…"
            if len(parts) >= 2:
                dirs.add("/".join(parts[:2]))
                has_runs = True
        if not has_runs:
            # žádné runy pro tuhle sadu → smaž podle aktuální kombinace slugů
            if project.slug and su.slug:
                dirs.add(f"{project.slug}/{su.slug}")

    # 3) Smazat tyto adresáře a vyčistit prázdné rodiče až k <project>
    for rel_dir in dirs:
        abs_dir = safe_join(base, rel_dir)
        if abs_dir:
            _rm_tree_safe(abs_dir)
            _prune_empty_dirs(rel_dir, stop_at=project.slug)  # ostatní sekvence v projektu zůstanou

    # 4) DB – CASCADE odstraní děti i jejich runs
    db.session.delete(s)
    db.session.commit()
    flash("Sada smazána.", "success")
    return redirect(url_for("admin.suites", project_id=project.id))

######################### RUN ROUTES #########################################

@admin_bp.route("/storage/reports/<path:filename>")
def storage_reports(filename):
    base_dir = _reports_base()
    # safe_join chrání proti traversal
    return send_from_directory(base_dir, filename, conditional=True)

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

    base_dir = _reports_base()
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

    def _back():
        nxt = request.form.get("next") or request.referrer or url_for("admin.projects")
        return redirect(nxt, code=303)  # 303 = See Other, nevyvolá znovu POST po F5

    f = request.files.get("csv")
    label = (request.form.get("label") or "").strip()

    if not f or not f.filename:
        flash("Vyber CSV soubor.", "error")
        return _back()
    if not _allowed_csv(f.filename):
        flash("Povolené jsou jen .csv soubory.", "error")
        return _back()

    ts   = datetime.utcnow().strftime("%Y-%m-%d_%H%M%S")
    safe = secure_filename(f.filename) or "report.csv"

    rel_dir  = f"{project.slug}/{suite.slug}"
    abs_dir  = os.path.join(_reports_base(), rel_dir)
    os.makedirs(abs_dir, exist_ok=True)

    rel_path = f"{rel_dir}/{ts}-{safe}"
    abs_path = os.path.join(_reports_base(), rel_path)
    f.save(abs_path)

    run = Run(project_id=project.id, suite_id=suite.id,
              label=label or os.path.splitext(safe)[0],
              csv_path=rel_path)
    db.session.add(run)
    db.session.commit()

    flash("CSV nahráno.", "success")
    return _back()


@admin_bp.post("/projects/<int:project_id>/suites/<int:suite_id>/runs/<int:run_id>/delete")
def runs_delete(project_id: int, suite_id: int, run_id: int):
    if not session.get("is_admin"):
        return redirect(url_for("admin.login", next=request.path))

    run = Run.query.filter_by(id=run_id, project_id=project_id, suite_id=suite_id).first_or_404()

    # 1) Smazat soubor
    rel = (run.csv_path or "").lstrip("/\\")
    _rm_file_safe(rel)

    # 2) Zkus vyčistit prázdné složky až k '<project>/<suite>'
    #    z rel cesty vezmeme první dva segmenty
    parts = rel.split("/", 2)
    if len(parts) >= 2:
        stop_at = "/".join(parts[:2])   # <project>/<suite>
        _prune_empty_dirs(rel, stop_at=stop_at)

    db.session.delete(run)
    db.session.commit()

    flash("Běh smazán.", "success")
    return redirect(url_for("admin.runs_list", project_id=project_id, suite_id=suite_id))

# =============================================================================
# PUBLIC BLUEPRINT – projektový zámek (heslo)
# =============================================================================
bp = Blueprint("bp", __name__, template_folder="templates")

_SESSION_KEY = "unlocked_projects"  # dict[str(project_id)] -> True

def _is_unlocked(project_id: int) -> bool:
    return bool(session.get(_SESSION_KEY, {}).get(str(project_id)))

def _require_project_access(project: Project):
    if session.get("is_admin"):
        return None
    if project.passphrase_hash and not _is_unlocked(project.id):
        nxt = request.full_path if request.query_string else request.path
        return redirect(url_for("bp.project_unlock", slug=project.slug, next=nxt))
    return None

@bp.route("/projects/<slug>/unlock", methods=["GET", "POST"])
def project_unlock(slug: str):
    project = Project.query.filter_by(slug=slug).first_or_404()

    if _is_unlocked(project.id) or session.get("is_admin"):
        dest = request.args.get("next") or url_for("bp.project_detail_public", slug=project.slug)
        return redirect(dest)

    if request.method == "POST":
        pwd = (request.form.get("passphrase") or "").strip()
        if project.verify_passphrase(pwd):
            unlocked = session.get(_SESSION_KEY) or {}
            unlocked[str(project.id)] = True
            session[_SESSION_KEY] = unlocked
            flash("Projekt odemčen.", "success")
            dest = request.args.get("next") or url_for("bp.project_detail_public", slug=project.slug)
            return redirect(dest)
        else:
            flash("Nesprávné heslo.", "error")

    return render_template("public/project_unlock.html", project=project)

@bp.get("/projects")
def public_projects_list():
    return render_template("public/projects_list.html")

@bp.get("/projects/<slug>")
def project_detail_public(slug: str):
    project = Project.query.filter_by(slug=slug).first_or_404()
    guard = _require_project_access(project)
    if guard:
        return guard
    return render_template("public/project_detail.html", project=project)
