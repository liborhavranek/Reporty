# seed_dokladujto.py
from __future__ import annotations

from typing import Dict, List, Optional
from datetime import datetime

from app import db  # tvůj SQLAlchemy instance
from app.models.project_model import Project, ProjectType, Visibility
from app.models.suite_model import Suite

from flask import Flask

# Pokud máš app-factory (create_app), naimportuj ji; jinak importuj přímo app z __init__.py
try:
    from app import create_app  # type: ignore
    app: Flask = create_app()
except Exception:
    # fallback: někteří mají rovnou `app` v app/__init__.py
    from app import app as _app  # type: ignore
    app = _app


# ----- Datová definice – SECTIONS (sekce) + CHILDREN (sekvence) -----
# name = název v UI; desc = popisek; order = pořadí; children = list sekvencí
DataDef = Dict[str, object]

SEED: List[DataDef] = [
    {
        "name": "DMS",
        "desc": "Testuje modul DMS – vytváření složek a souborů, přesuny, mazání a oprávnění.",
        "order": 10,
        "children": [
            {"name": "Set1", "desc": "Základní CRUD nad soubory/složkami v DMS.", "order": 10},
            {"name": "Set2", "desc": "Hromadné operace a přesuny napříč stromy.", "order": 20},
            {"name": "Set3", "desc": "Oprávnění: čtení/zápis, sdílení, audit.", "order": 30},
            {"name": "Set4", "desc": "Integrace s vyhledáváním a verzemi.", "order": 40},
            {"name": "Set5", "desc": "Okrajové stavy a regresní scénáře.", "order": 50},
        ],
    },
    {
        "name": "invoice-vat-payer-accounting",
        "desc": "Faktury pro plátce DPH s napojeným účetnictvím – základní průchod od vystavení po zaúčtování.",
        "order": 20,
        "children": [
            {"name": "01-invoice-cz-currency", "desc": "CZK faktura – vystavení, kontrola položek, výpočet DPH.", "order": 10},
            {"name": "02-invoice-eur-currency", "desc": "EUR faktura – kurz ČNB/ECB, DPH v cizí měně, zaokrouhlení.", "order": 20},
            {"name": "03-basic-info-and-contact", "desc": "Validace hlavičky a odběratele v adresáři.", "order": 30},
            {"name": "04-datum-and-payment", "desc": "Splatnost, platební metody, VS/SS, QR.", "order": 40},
            {"name": "05-invoice-item", "desc": "Položky, sazby, soupis daní a kontrola součtů.", "order": 50},
        ],
    },
    {
        "name": "invoice-no-vat-payer-accounting",
        "desc": "Faktury pro neplátce DPH – jednoduché vystavení a účetní dopady bez DPH.",
        "order": 30,
        "children": [
            {"name": "01-invoice-cz-currency", "desc": "CZK faktura bez DPH – částky a součty.", "order": 10},
            {"name": "02-invoice-eur-currency", "desc": "EUR faktura bez DPH – přepočty a zaokrouhlení.", "order": 20},
            {"name": "03-basic-info-and-contact", "desc": "Hlavička dokladu + kontakt.", "order": 30},
            {"name": "04-datum-and-payment", "desc": "Termíny, splatnost, variabilní symbol.", "order": 40},
            {"name": "05-invoice-item", "desc": "Položky a kontrola částek.", "order": 50},
        ],
    },
    {
        "name": "registration",
        "desc": "Registrační scénáře – všechny typy subjektů a validace vstupů.",
        "order": 40,
        "children": [
            {"name": "FO",   "desc": "Fyzická osoba – základní registrace.", "order": 10},
            {"name": "FO-DE","desc": "Fyzická osoba – Německo (lokální formáty).", "order": 20},
            {"name": "PO",   "desc": "Právnická osoba – CZ.", "order": 30},
            {"name": "PO-DE","desc": "Právnická osoba – Německo.", "order": 40},
            {"name": "PO-NO","desc": "Právnická osoba – Norsko (specifika DIČ).", "order": 50},
        ],
    },
    {
        "name": "DMS-accounting-one",
        "desc": "Dlouhé end-to-end sekvence – vytvoření dokladů v DMS a průchod do účetnictví.",
        "order": 50,
        "children": [
            {"name": "FP",  "desc": "Faktura přijatá – od importu po zaúčtování.", "order": 10},
            {"name": "OZ",  "desc": "Ostatní závazek – schvalování a účetní předpis.", "order": 20},
            {"name": "VPD", "desc": "Výdajový pokladní doklad – pokladna a saldokonto.", "order": 30},
        ],
    },
    {
        "name": "DMS-accounting-two",
        "desc": "Krátké sekvence – rychlejší průchody, regresní testy účetních dokladů.",
        "order": 60,
        "children": [
            {"name": "FV",          "desc": "Faktura vydaná – vystavení a párování plateb.", "order": 10},
            {"name": "FV-faktury",  "desc": "Regresní sada vícero FV s variacemi DPH.", "order": 20},
            {"name": "OP",          "desc": "Ostatní pohledávka – zaúčtování a maturity.", "order": 30},
            {"name": "PPD",         "desc": "Příjmový pokladní doklad – párování a účty.", "order": 40},
            {"name": "PPD-faktury", "desc": "Kompozitní scénáře PPD + několik faktur.", "order": 50},
        ],
    },
    {
        "name": "DMS-accounting-three",
        "desc": "Sekvence pro neplátce – doklady bez DPH a jejich účetní dopady.",
        "order": 70,
        "children": [
            {"name": "FP-neplatce",  "desc": "Faktura přijatá bez DPH – účtování nákladů.", "order": 10},
            {"name": "FV-neplatce",  "desc": "Faktura vydaná bez DPH – výnosy, saldokonto.", "order": 20},
            {"name": "OP-neplatce",  "desc": "Ostatní pohledávka bez DPH.", "order": 30},
            {"name": "OZ-neplatce",  "desc": "Ostatní závazek bez DPH.", "order": 40},
            {"name": "PPD-neplatce", "desc": "Příjmový pokladní doklad – bez DPH.", "order": 50},
            {"name": "VPD-neplatce", "desc": "Výdajový pokladní doklad – bez DPH.", "order": 60},
        ],
    },
]


def get_or_create_project(name: str) -> Project:
    p = Project.query.filter_by(name=name).first()
    if p:
        # zaktualizujeme jen to, co nás zajímá (nezbouráme heslo, slugy atd.)
        p.type = ProjectType.e2e
        p.visibility = Visibility.public
        if not p.description:
            p.description = "Veřejný E2E projekt s kompletním coverage účetních a DMS scénářů."
        p.ensure_unique_slug()
        db.session.commit()
        return p

    p = Project(
        name=name,
        type=ProjectType.e2e,
        visibility=Visibility.public,
        description="Veřejný E2E projekt s kompletním coverage účetních a DMS scénářů.",
    )
    # žádné heslo – public; kdybys chtěl zamknout: p.set_passphrase("tajneheslo")
    p.ensure_unique_slug()
    db.session.add(p)
    db.session.commit()
    return p


def get_or_create_suite(project_id: int, name: str, parent_id: Optional[int], desc: Optional[str], order_index: int) -> Suite:
    # Slug je unikátní v rámci (project_id, parent_id), proto hledáme podle těchto hodnot + jména.
    # Pokud už existuje stejná kombinace (název/sluggish), vrátíme ji; jinak vytvoříme.
    existing = Suite.query.filter_by(project_id=project_id, parent_id=parent_id, name=name).first()
    if existing:
        # drobná údržba
        existing.description = existing.description or desc
        if existing.order_index != order_index:
            existing.order_index = order_index
        existing.ensure_unique_slug()
        db.session.commit()
        return existing

    s = Suite(
        project_id=project_id,
        parent_id=parent_id,
        name=name,
        description=desc,
        order_index=order_index,
        is_active=True,
    )
    s.ensure_unique_slug()
    db.session.add(s)
    db.session.commit()
    return s


def seed() -> None:
    with app.app_context():
        project = get_or_create_project("dokladujto")

        # Sekce + děti
        for sec in SEED:
            section = get_or_create_suite(
                project_id=project.id,
                name=str(sec["name"]),
                parent_id=None,
                desc=str(sec.get("desc") or ""),
                order_index=int(sec.get("order") or 0),
            )

            children = sec.get("children") or []
            for child in children:  # type: ignore
                get_or_create_suite(
                    project_id=project.id,
                    name=str(child["name"]),
                    parent_id=section.id,
                    desc=str(child.get("desc") or ""),
                    order_index=int(child.get("order") or 0),
                )

        print("✅ Seed hotový.")
        print(f"Projekt: {project.name} (slug: {project.slug}, visibility: {project.visibility.value})")
        print(f"Počet sekcí: {Suite.query.filter_by(project_id=project.id, parent_id=None).count()}")
        print(f"Počet sekvencí: {Suite.query.filter(Suite.project_id==project.id, Suite.parent_id.isnot(None)).count()}")


if __name__ == "__main__":
    seed()
