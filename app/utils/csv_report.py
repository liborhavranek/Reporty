# app/utils/csv_report.py
from __future__ import annotations
import csv, io, os
from datetime import datetime

STATUSES_OK = {"passed", "ok", "success"}
STATUSES_FAIL = {"failed", "fail", "error"}
STATUSES_SKIP = {"skipped", "pending", "skip"}

def _ms_fmt(ms: int) -> str:
    try:
        ms = int(ms)
    except Exception:
        return str(ms)
    s = ms // 1000
    rem_ms = ms % 1000
    m = s // 60
    s = s % 60
    if m:
        return f"{m:d}:{s:02d}.{rem_ms:03d}"
    return f"{s:d}.{rem_ms:03d}s"

def parse_report_csv(abs_path: str) -> dict:
    """
    Vrátí:
      {
        'file_name': '2025_09_11_14_47.csv',
        'header_note': 'Text poznámky z hlavičky CSV nebo None',
        'rows': [ {describe, test, status, duration_ms, duration_fmt, timestamp, timestampLocal}, ... ],
        'groups': [...],
        'summary': {...},
      }
    """
    if not os.path.exists(abs_path):
        raise FileNotFoundError(abs_path)

    # Načti soubor a získej hlavičkové komentáře (poznámku)
    with open(abs_path, "rb") as f:
        raw = f.read()
    text = raw.decode("utf-8-sig", errors="replace")

    orig_lines = text.splitlines()

    # --- NOVÉ: vyzobnout poznámku z horních komentářů -----------------------
    header_comment_lines = []
    data_start_index = 0
    for idx, ln in enumerate(orig_lines):
        s = ln.strip()
        if not s:
            # prázdné řádky nadále povolíme před komentáři
            data_start_index = idx + 1
            continue
        if s.startswith("#"):
            # sbíráme komentáře; data ještě nezačala
            header_comment_lines.append(s.lstrip("#").strip())
            data_start_index = idx + 1
            continue
        # jakmile narazíme na první nekomentovaný neprázdný řádek, končíme
        data_start_index = idx
        break

    header_note = None
    if header_comment_lines:
        # spojíme více komentářů do jednoho odstavce (zachováme pořadí)
        header_note = "\n".join([ln for ln in header_comment_lines if ln])

    # --- Původní parsování: vynecháme všechny komentáře (kdekoli v souboru) --
    # Poznámku už máme z horní části; pro CSV data chceme jen řádky bez komentářů.
    lines = [ln for ln in orig_lines if not ln.strip().startswith("#")]

    rdr = csv.DictReader(io.StringIO("\n".join(lines)))

    rows = []
    total = passed = failed = skipped = 0
    total_ms = 0
    for r in rdr:
        desc = (r.get("describe") or "").strip()
        test = (r.get("test") or "").strip()
        status_raw = (r.get("status") or "").strip().lower()
        dur = r.get("duration") or "0"
        try:
            dur_ms = int(float(dur))
        except Exception:
            dur_ms = 0
        ts = (r.get("timestamp") or "").strip()
        tsl = (r.get("timestampLocal") or "").strip()

        total += 1
        total_ms += dur_ms
        if status_raw in STATUSES_OK:
            passed += 1
            status_norm = "passed"
        elif status_raw in STATUSES_FAIL:
            failed += 1
            status_norm = "failed"
        elif status_raw in STATUSES_SKIP:
            skipped += 1
            status_norm = "skipped"
        else:
            status_norm = status_raw or "unknown"

        rows.append({
            "describe": desc,
            "test": test,
            "status": status_norm,
            "duration_ms": dur_ms,
            "duration_fmt": _ms_fmt(dur_ms),
            "timestamp": ts,
            "timestampLocal": tsl,
        })

    pass_rate = round((passed / total * 100.0), 1) if total else 0.0

    # Seskupení podle "describe"
    groups_map = {}
    for r in rows:
        g = groups_map.setdefault(r["describe"] or "—", {
            "describe": r["describe"] or "—",
            "total": 0, "passed": 0, "failed": 0, "skipped": 0,
            "duration_ms": 0, "tests": []
        })
        g["tests"].append(r)
        g["total"] += 1
        g["duration_ms"] += r["duration_ms"]
        if r["status"] == "passed": g["passed"] += 1
        elif r["status"] == "failed": g["failed"] += 1
        elif r["status"] == "skipped": g["skipped"] += 1

    groups = []
    for g in groups_map.values():
        g["duration_fmt"] = _ms_fmt(g["duration_ms"])
        groups.append(g)

    return {
        "file_name": os.path.basename(abs_path),
        "header_note": header_note,   # ← NOVÉ
        "rows": rows,
        "groups": groups,
        "summary": {
            "total": total, "passed": passed, "failed": failed, "skipped": skipped,
            "pass_rate": pass_rate,
            "duration_ms": total_ms, "duration_fmt": _ms_fmt(total_ms),
        }
    }
