import pytest

from tests.db_guard import UnsafeTestDatabaseError, check_destructive_target

SAFE_URL = "postgresql+asyncpg://leadops_migrator:x@localhost:5434/leadops_test"
OPT_IN = {"ALLOW_DESTRUCTIVE_TEST_DB": "true"}


def test_local_test_database_with_opt_in_is_allowed() -> None:
    check_destructive_target(SAFE_URL, OPT_IN)


@pytest.mark.parametrize("host", ["127.0.0.1", "[::1]"])
def test_loopback_addresses_are_local(host: str) -> None:
    check_destructive_target(f"postgresql://u:p@{host}:5432/leadops_test", OPT_IN)


@pytest.mark.parametrize("value", [None, "", "1", "yes", "TRUE", "True"])
def test_without_the_exact_opt_in_it_refuses(value: str | None) -> None:
    environ = {} if value is None else {"ALLOW_DESTRUCTIVE_TEST_DB": value}

    with pytest.raises(UnsafeTestDatabaseError, match="ALLOW_DESTRUCTIVE_TEST_DB"):
        check_destructive_target(SAFE_URL, environ)


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://u:p@db.example.com:5432/leadops_test",
        "postgresql://u:p@10.0.0.5:5432/leadops_test",
        "postgresql://u:p@db:5432/leadops_test",
    ],
)
def test_non_local_hosts_are_refused(url: str) -> None:
    with pytest.raises(UnsafeTestDatabaseError, match="not local"):
        check_destructive_target(url, OPT_IN)


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://u:p@localhost:5434/leadops",
        "postgresql://u:p@localhost:5434/leadops_test_backup",
        "postgresql://u:p@localhost:5434/",
    ],
)
def test_databases_not_named_test_are_refused(url: str) -> None:
    with pytest.raises(UnsafeTestDatabaseError, match="does not end in"):
        check_destructive_target(url, OPT_IN)
