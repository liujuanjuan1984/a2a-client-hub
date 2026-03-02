from __future__ import annotations

from sqlalchemy.exc import DBAPIError

from app.db.locking import (
    DbLockFailureKind,
    RetryableDbLockError,
    RetryableDbQueryTimeoutError,
    classify_postgres_lock_failure,
    is_retryable_db_lock_failure,
    is_retryable_db_query_timeout,
    to_retryable_db_lock_error,
    to_retryable_db_query_timeout_error,
)


def _build_dbapi_error(*, sqlstate: str | None = None, message: str = "") -> DBAPIError:
    class _OrigError(Exception):
        pass

    orig = _OrigError(message)
    if sqlstate is not None:
        setattr(orig, "sqlstate", sqlstate)
    return DBAPIError(statement="SELECT 1", params={}, orig=orig)


def test_classify_postgres_lock_failure_with_sqlstate_lock_not_available() -> None:
    exc = _build_dbapi_error(sqlstate="55P03", message="lock not available")
    assert classify_postgres_lock_failure(exc) == DbLockFailureKind.LOCK_NOT_AVAILABLE
    assert is_retryable_db_lock_failure(exc) is True


def test_classify_postgres_lock_failure_with_lock_marker_message() -> None:
    exc = _build_dbapi_error(message="could not obtain lock on row")
    assert classify_postgres_lock_failure(exc) == DbLockFailureKind.LOCK_NOT_AVAILABLE
    assert is_retryable_db_lock_failure(exc) is True


def test_classify_postgres_lock_failure_ignores_statement_timeout() -> None:
    exc = _build_dbapi_error(
        sqlstate="57014",
        message="canceling statement due to statement timeout",
    )
    assert classify_postgres_lock_failure(exc) is None
    assert is_retryable_db_lock_failure(exc) is False


def test_query_timeout_detection_requires_sqlstate_and_timeout_marker() -> None:
    timeout_exc = _build_dbapi_error(
        sqlstate="57014",
        message="canceling statement due to statement timeout",
    )
    canceled_non_timeout_exc = _build_dbapi_error(
        sqlstate="57014",
        message="canceling statement",
    )
    timeout_text_without_sqlstate_exc = _build_dbapi_error(
        message="canceling statement due to statement timeout",
    )

    assert is_retryable_db_query_timeout(timeout_exc) is True
    assert is_retryable_db_query_timeout(canceled_non_timeout_exc) is False
    assert is_retryable_db_query_timeout(timeout_text_without_sqlstate_exc) is False


def test_to_retryable_db_lock_error_maps_only_lock_contention() -> None:
    lock_exc = _build_dbapi_error(sqlstate="55P03", message="lock not available")
    timeout_exc = _build_dbapi_error(
        sqlstate="57014",
        message="canceling statement due to statement timeout",
    )

    mapped_lock = to_retryable_db_lock_error(lock_exc, lock_message="lock busy")
    mapped_timeout = to_retryable_db_lock_error(timeout_exc, lock_message="lock busy")

    assert isinstance(mapped_lock, RetryableDbLockError)
    assert mapped_lock.kind == DbLockFailureKind.LOCK_NOT_AVAILABLE
    assert str(mapped_lock) == "lock busy"
    assert mapped_timeout is None


def test_to_retryable_db_query_timeout_error_maps_timeout_only() -> None:
    timeout_exc = _build_dbapi_error(
        sqlstate="57014",
        message="canceling statement due to statement timeout",
    )
    lock_exc = _build_dbapi_error(sqlstate="55P03", message="lock not available")

    mapped_timeout = to_retryable_db_query_timeout_error(
        timeout_exc,
        timeout_message="query timeout",
    )
    mapped_lock = to_retryable_db_query_timeout_error(
        lock_exc,
        timeout_message="query timeout",
    )

    assert isinstance(mapped_timeout, RetryableDbQueryTimeoutError)
    assert str(mapped_timeout) == "query timeout"
    assert mapped_lock is None


def test_converter_returns_existing_retryable_errors() -> None:
    lock_exc = RetryableDbLockError(
        "retry lock", kind=DbLockFailureKind.LOCK_NOT_AVAILABLE
    )
    timeout_exc = RetryableDbQueryTimeoutError("retry timeout")

    assert to_retryable_db_lock_error(lock_exc, lock_message="lock busy") is lock_exc
    assert (
        to_retryable_db_query_timeout_error(
            timeout_exc,
            timeout_message="query timeout",
        )
        is timeout_exc
    )
