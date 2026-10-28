import pytest
from pydantic import ValidationError

from intentcut.backend.shared.settings import BackendSettings


def test_settings_hide_database_secret(settings):
    assert "unused:unused" not in repr(settings)
    assert settings.media_root.is_absolute()


@pytest.mark.parametrize(
    "url", ["sqlite:///test.db", "postgresql://user:secret@localhost/db", "garbage"]
)
def test_non_psycopg_urls_are_rejected_without_echoing_secrets(url):
    with pytest.raises(ValidationError) as error:
        BackendSettings(_env_file=None, database_url=url)
    assert url not in str(error.value)


def test_limits_must_be_consistent():
    with pytest.raises(ValidationError):
        BackendSettings(
            _env_file=None,
            database_url="postgresql+psycopg://localhost/test",
            max_file_bytes=100,
            max_request_bytes=10,
        )
