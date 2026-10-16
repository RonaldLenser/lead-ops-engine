"""Typed application settings, loaded once from environment variables.

Every value is validated at startup. A missing or unsafe setting stops the
process immediately with a clear message, instead of failing later in the
middle of a request. Settings are added here only when code uses them.

Two rules protect credentials:

1. Connection strings are SecretStr, so they never appear in repr(), logs,
   or tracebacks by accident. Call .get_secret_value() only where the value
   is actually used.
2. hide_input_in_errors=True: a rejected value is never echoed back in a
   validation error, because those errors end up in terminals and logs.
"""

import re
from functools import lru_cache
from ipaddress import IPv4Network, IPv6Network
from typing import Literal, Self
from urllib.parse import urlsplit

import phonenumbers
from pydantic import Field, IPvAnyNetwork, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

AppEnv = Literal["local", "test", "prod"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]

_POSTGRES_SCHEMES = ("postgres", "postgresql", "postgresql+asyncpg")
_ASYNC_SCHEME = "postgresql+asyncpg"

# Passwords that appear in this repository (local Compose and CI). They are
# fine for a throwaway local database and must never reach production.
DEV_DATABASE_PASSWORDS = frozenset(
    {"leadops_app_dev", "leadops_migrator_dev", "postgres", "password", "changeme"}
)
SUPERUSER_NAMES = frozenset({"postgres"})

SOURCE_NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
MIN_WEBHOOK_SECRET_LENGTH = 32


def normalize_database_url(raw: str) -> str:
    """Return the URL with the async driver scheme SQLAlchemy needs.

    Accepts postgres://, postgresql://, and postgresql+asyncpg://.
    Error messages describe the problem without including the value.
    """
    scheme, sep, rest = raw.partition("://")
    if not sep or scheme not in _POSTGRES_SCHEMES:
        raise ValueError("must be a PostgreSQL URL (postgresql://user:password@host:port/db)")
    if not rest or rest.startswith("/"):
        raise ValueError("must include a host")
    return f"{_ASYNC_SCHEME}://{rest}"


def _production_problems(name: str, url: SecretStr) -> list[str]:
    """Reasons this connection string is unsafe for production (empty list = fine)."""
    parts = urlsplit(url.get_secret_value())
    problems: list[str] = []
    if not parts.password:
        problems.append(f"{name} has no password")
    elif parts.password in DEV_DATABASE_PASSWORDS:
        problems.append(f"{name} uses a development password")
    if parts.username in SUPERUSER_NAMES:
        problems.append(f"{name} connects as a superuser")
    return problems


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # .env may hold settings for later milestones
        str_strip_whitespace=True,  # secrets pasted from managers often gain a newline
        hide_input_in_errors=True,
    )

    # ----- App -----
    app_env: AppEnv = "local"
    log_level: LogLevel = "INFO"

    # ----- Database -----
    # The application's own role: data access only, no DDL (see infra/postgres/init).
    # Required, no default: production can never silently fall back to localhost.
    database_url: SecretStr
    # The schema owner role, used only by Alembic. Optional: falls back to database_url.
    migration_database_url: SecretStr | None = None
    db_pool_size: int = Field(default=5, ge=1, le=50)
    db_connect_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    db_echo: bool = False  # logs every SQL statement; local debugging only

    # ----- Health -----
    readiness_timeout_seconds: float = Field(default=2.0, gt=0, le=10)

    # ----- Intake -----
    # Hard cap on any request body (approved: 32 KB).
    max_request_body_bytes: int = Field(default=32_768, ge=1_024, le=1_048_576)
    # Region used to read phone numbers that have no country code.
    default_phone_region: str = "US"
    # Raw inbound payloads are purged after this many days. The purge job is
    # built in M9; until then this value is configuration only.
    raw_event_retention_days: int = Field(default=30, ge=1, le=3650)

    # ----- Webhooks -----
    # JSON object: source name -> list of shared secrets (several = rotation).
    # Example: {"website_form": ["<at least 32 random characters>"]}
    webhook_secrets: dict[str, list[SecretStr]] = Field(default_factory=dict)
    webhook_timestamp_tolerance_seconds: int = Field(default=300, ge=30, le=900)

    # ----- Client IP / proxies -----
    # Only peers inside these networks may set X-Forwarded-For. Empty = trust none.
    trusted_proxy_cidrs: list[IPvAnyNetwork] = Field(default_factory=list)

    # ----- Rate limits (per process, requests per minute) -----
    rate_limit_intake_per_ip: int = Field(default=60, ge=1, le=100_000)
    rate_limit_intake_per_api_key: int = Field(default=120, ge=1, le=100_000)
    rate_limit_webhook_per_source: int = Field(default=120, ge=1, le=100_000)

    @field_validator("database_url", "migration_database_url", mode="before")
    @classmethod
    def _normalize_url(cls, value: object) -> object:
        if value is None or value == "":
            # Compose passes unset variables as "". Treat that as "not set";
            # the required database_url still fails as missing.
            return None
        raw = value.get_secret_value() if isinstance(value, SecretStr) else value
        if not isinstance(raw, str):
            raise ValueError("must be a string")
        # A "before" validator sees the raw input, before str_strip_whitespace
        # applies, so strip here explicitly.
        return SecretStr(normalize_database_url(raw.strip()))

    @field_validator("default_phone_region")
    @classmethod
    def _known_region(cls, value: str) -> str:
        region = value.upper()
        if region not in phonenumbers.SUPPORTED_REGIONS:
            raise ValueError("must be a two-letter region code such as US")
        return region

    @field_validator("webhook_secrets")
    @classmethod
    def _valid_webhook_secrets(
        cls, value: dict[str, list[SecretStr]]
    ) -> dict[str, list[SecretStr]]:
        for source, secrets in value.items():
            if not SOURCE_NAME.fullmatch(source):
                raise ValueError("source names must be lowercase letters, digits, _ or -")
            if not secrets:
                raise ValueError("each webhook source needs at least one secret")
            if any(len(s.get_secret_value()) < MIN_WEBHOOK_SECRET_LENGTH for s in secrets):
                raise ValueError(
                    f"webhook secrets must be at least {MIN_WEBHOOK_SECRET_LENGTH} characters"
                )
        return value

    @model_validator(mode="after")
    def _check_production_safety(self) -> Self:
        if self.app_env != "prod":
            return self
        problems = _production_problems("DATABASE_URL", self.database_url)
        if self.migration_database_url is not None:
            problems += _production_problems("MIGRATION_DATABASE_URL", self.migration_database_url)
            app_user = urlsplit(self.database_url.get_secret_value()).username
            migration_user = urlsplit(self.migration_database_url.get_secret_value()).username
            if app_user == migration_user:
                problems.append("DATABASE_URL and MIGRATION_DATABASE_URL use the same role")
        if self.db_echo:
            problems.append("DB_ECHO must be false (SQL logging can expose personal data)")
        if problems:
            raise ValueError("Unsafe production settings: " + "; ".join(problems))
        return self

    @property
    def json_logs(self) -> bool:
        """Machine-readable logs everywhere except a developer's terminal."""
        return self.app_env != "local"

    @property
    def effective_migration_url(self) -> SecretStr:
        return self.migration_database_url or self.database_url

    @property
    def trusted_proxy_networks(self) -> list[IPv4Network | IPv6Network]:
        return list(self.trusted_proxy_cidrs)


@lru_cache
def get_settings() -> Settings:
    """Build settings once per process (values come from the environment)."""
    return Settings()  # type: ignore[call-arg]
