import pytest
from pydantic import SecretStr, ValidationError

from leadops.config import Settings, normalize_database_url

APP_URL = "postgresql+asyncpg://leadops_app:leadops_app_dev@localhost:5434/leadops"
PROD_APP_URL = "postgresql://leadops_app:Str0ng-app-pw@db:5432/leadops"
PROD_MIGRATION_URL = "postgresql://leadops_migrator:Str0ng-migrator-pw@db:5432/leadops"


def build(**values: object) -> Settings:
    return Settings(_env_file=None, **values)  # type: ignore[call-arg, arg-type]


def secret(value: SecretStr | None) -> str:
    assert value is not None
    return value.get_secret_value()


# ----- loading and normalization -----


def test_valid_settings_load_with_local_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    # CI sets APP_ENV=test; remove it so this test checks the real default.
    monkeypatch.delenv("APP_ENV", raising=False)

    settings = build(database_url=APP_URL)

    assert secret(settings.database_url) == APP_URL
    assert settings.app_env == "local"
    assert settings.json_logs is False


@pytest.mark.parametrize("scheme", ["postgres", "postgresql", "postgresql+asyncpg"])
def test_postgres_schemes_are_normalized_to_asyncpg(scheme: str) -> None:
    settings = build(database_url=f"{scheme}://u:p@h:5432/db")

    assert secret(settings.database_url) == "postgresql+asyncpg://u:p@h:5432/db"


@pytest.mark.parametrize(
    "url", ["mysql://u:p@h/db", "not a url", "postgresql://", "postgresql:///db"]
)
def test_non_postgres_or_hostless_urls_are_rejected(url: str) -> None:
    with pytest.raises(ValueError, match=r"PostgreSQL URL|host"):
        normalize_database_url(url)


def test_missing_database_url_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(ValidationError, match="database_url"):
        build()


def test_empty_database_url_counts_as_missing() -> None:
    with pytest.raises(ValidationError, match="database_url"):
        build(database_url="")


def test_empty_migration_url_means_unset() -> None:
    settings = build(database_url=APP_URL, migration_database_url="")

    assert settings.migration_database_url is None
    assert settings.effective_migration_url == settings.database_url


def test_trailing_whitespace_is_stripped() -> None:
    settings = build(database_url=APP_URL + "\r\n")

    assert secret(settings.database_url) == APP_URL


def test_invalid_log_level_is_rejected() -> None:
    with pytest.raises(ValidationError):
        build(database_url=APP_URL, log_level="LOUD")


def test_pool_size_bounds_are_enforced() -> None:
    with pytest.raises(ValidationError):
        build(database_url=APP_URL, db_pool_size=0)


def test_non_local_envs_use_json_logs() -> None:
    assert build(database_url=APP_URL, app_env="test").json_logs is True


# ----- secrets never leak -----


def test_connection_strings_are_hidden_in_repr() -> None:
    settings = build(database_url=APP_URL, migration_database_url=PROD_MIGRATION_URL)

    assert "leadops_app_dev" not in repr(settings)
    assert "Str0ng-migrator-pw" not in repr(settings)


def test_validation_errors_never_echo_the_rejected_value() -> None:
    with pytest.raises(ValidationError) as excinfo:
        build(database_url="mysql://user:hunter2-secret@host/db")

    assert "hunter2-secret" not in str(excinfo.value)


# ----- production safety -----


def test_production_settings_with_separate_strong_roles_load() -> None:
    settings = build(
        app_env="prod", database_url=PROD_APP_URL, migration_database_url=PROD_MIGRATION_URL
    )

    assert settings.app_env == "prod"


@pytest.mark.parametrize(
    ("database_url", "expected"),
    [
        ("postgresql://leadops_app:leadops_app_dev@db/leadops", "development password"),
        ("postgresql://leadops_app@db/leadops", "no password"),
        ("postgresql://postgres:Str0ng-pw@db/leadops", "superuser"),
    ],
)
def test_production_rejects_unsafe_app_credentials(database_url: str, expected: str) -> None:
    with pytest.raises(ValidationError, match=expected) as excinfo:
        build(app_env="prod", database_url=database_url)

    assert "Str0ng-pw" not in str(excinfo.value)


def test_production_rejects_dev_migration_password() -> None:
    with pytest.raises(ValidationError, match="MIGRATION_DATABASE_URL uses a development"):
        build(
            app_env="prod",
            database_url=PROD_APP_URL,
            migration_database_url="postgresql://leadops_migrator:leadops_migrator_dev@db/leadops",
        )


def test_production_rejects_app_and_migrator_sharing_one_role() -> None:
    with pytest.raises(ValidationError, match="same role"):
        build(
            app_env="prod",
            database_url=PROD_APP_URL,
            migration_database_url="postgresql://leadops_app:Other-strong-pw@db/leadops",
        )


def test_production_rejects_sql_echo() -> None:
    with pytest.raises(ValidationError, match="DB_ECHO"):
        build(app_env="prod", database_url=PROD_APP_URL, db_echo=True)


def test_dev_credentials_are_allowed_outside_production() -> None:
    settings = build(app_env="local", database_url=APP_URL, db_echo=True)

    assert settings.db_echo is True


# ----- intake settings (M2) -----


def test_intake_defaults() -> None:
    settings = build(database_url=APP_URL)

    assert settings.max_request_body_bytes == 32_768
    assert settings.raw_event_retention_days == 30
    assert settings.trusted_proxy_networks == []
    assert settings.webhook_secrets == {}


def test_list_and_dict_settings_parse_from_json_environment_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TRUSTED_PROXY_CIDRS", '["172.18.0.0/16", "fd00::/8"]')
    monkeypatch.setenv("WEBHOOK_SECRETS", '{"website_form": ["' + "s" * 32 + '"]}')

    settings = build(database_url=APP_URL)

    assert [str(net) for net in settings.trusted_proxy_networks] == ["172.18.0.0/16", "fd00::/8"]
    assert secret(settings.webhook_secrets["website_form"][0]) == "s" * 32
    assert "s" * 32 not in repr(settings)


@pytest.mark.parametrize(
    ("secrets", "message"),
    [
        ({"website_form": ["too-short"]}, "at least 32"),
        ({"website_form": []}, "at least one secret"),
        ({"Website Form": ["s" * 32]}, "source names"),
    ],
)
def test_webhook_secrets_are_validated(secrets: dict[str, list[str]], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        build(database_url=APP_URL, webhook_secrets=secrets)


def test_invalid_proxy_cidr_is_rejected() -> None:
    with pytest.raises(ValidationError):
        build(database_url=APP_URL, trusted_proxy_cidrs=["not-a-network"])


def test_phone_region_is_validated_and_uppercased() -> None:
    assert build(database_url=APP_URL, default_phone_region="gb").default_phone_region == "GB"
    with pytest.raises(ValidationError, match="region code"):
        build(database_url=APP_URL, default_phone_region="XX")


def test_body_limit_bounds() -> None:
    with pytest.raises(ValidationError):
        build(database_url=APP_URL, max_request_body_bytes=10)
