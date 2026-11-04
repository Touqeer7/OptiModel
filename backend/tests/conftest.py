import pytest
from fastapi.testclient import TestClient

from backend.app.main import create_app


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        yield client
