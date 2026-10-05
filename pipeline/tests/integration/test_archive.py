from openfoodalerts.archive import ArchiveOutcome, archive, latest_raw
from openfoodalerts.db.connection import Connection


def put(db: Connection, body: bytes, key: str = "F-1") -> ArchiveOutcome:
    return archive(
        db,
        source="openfda",
        kind="detail",
        source_key=key,
        url="https://api.fda.gov/x",
        http_status=200,
        content_type="application/json",
        body=body,
    )


def test_first_fetch_is_new(db: Connection) -> None:
    outcome = put(db, b'{"a":1}')
    assert outcome.status == "new"
    assert outcome.raw_record_id is not None


def test_same_content_is_not_written_again(db: Connection) -> None:
    first = put(db, b'{"a":1}')
    second = put(db, b'{"a":1}')
    assert second.status == "unchanged"
    assert second.raw_record_id == first.raw_record_id


def test_changed_content_appends_a_row(db: Connection) -> None:
    first = put(db, b'{"a":1}')
    second = put(db, b'{"a":2}')
    assert second.status == "changed"
    assert second.raw_record_id != first.raw_record_id
    latest = latest_raw(db, source="openfda", kind="detail", source_key="F-1")
    assert latest is not None and latest.body == b'{"a":2}'


def test_reverting_to_old_content_is_a_change(db: Connection) -> None:
    put(db, b'{"a":1}')
    put(db, b'{"a":2}')
    assert put(db, b'{"a":1}').status == "changed"


def test_keys_are_independent(db: Connection) -> None:
    put(db, b'{"a":1}', key="F-1")
    assert put(db, b'{"a":1}', key="F-2").status == "new"
