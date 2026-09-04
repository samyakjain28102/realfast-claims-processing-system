"""Smoke tests for package layout and imports."""

import importlib


def test_app_package_imports() -> None:
    importlib.import_module("app")


def test_domain_modules_import() -> None:
    for name in (
        "money",
        "entities",
        "rules",
        "reasons",
        "accumulators",
        "engine",
        "lifecycle",
        "states",
    ):
        importlib.import_module(f"app.domain.{name}")


def test_application_modules_import() -> None:
    for name in (
        "submit_claim",
        "prior_duplicates",
        "resolve_review",
        "file_dispute",
        "mark_paid",
        "build_eob",
    ):
        importlib.import_module(f"app.application.{name}")


def test_infrastructure_and_api_import() -> None:
    importlib.import_module("app.infrastructure")
    importlib.import_module("app.infrastructure.db")
    importlib.import_module("app.infrastructure.mapping")
    importlib.import_module("app.infrastructure.repositories")
    importlib.import_module("app.api.main")
    importlib.import_module("app.seed.load")
