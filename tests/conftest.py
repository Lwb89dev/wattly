from __future__ import annotations

import os
from pathlib import Path

import pytest

# Deterministic language for the whole test-suite (host locale may be Italian).
os.environ["WATTLY_LANGUAGE"] = "en"

from wattly.app import create_app
from wattly.config import Config
from wattly.samples import build_sample_pdfs


@pytest.fixture()
def config(tmp_path) -> Config:
    return Config(data_dir=tmp_path, secret_key="test-secret", ocr_enabled=False)


@pytest.fixture()
def app(config):
    application = create_app(config)
    application.config.update(TESTING=True)
    return application


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def db_session(app):
    session = app.extensions["wattly_db"].session()
    try:
        yield session
        session.commit()
    finally:
        session.close()


@pytest.fixture()
def sample_pdfs(tmp_path) -> list[Path]:
    return build_sample_pdfs(tmp_path / "samples")


@pytest.fixture()
def pdf_bytes(sample_pdfs) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sample_pdfs}
