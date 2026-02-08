from __future__ import annotations

from datetime import date, datetime, time, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from app.utils.json_encoder import json_dumps

pytestmark = pytest.mark.unit


def test_json_dumps_encodes_common_types():
    class DummyModel:
        def __init__(self, value: int) -> None:
            self.value = value

        def model_dump(self) -> dict[str, int]:
            return {"value": self.value}

    sample_datetime = datetime(2024, 1, 1, 12, 30, tzinfo=timezone.utc)
    sample_date = date(2024, 1, 2)
    sample_time = time(8, 45)
    sample_uuid = uuid4()

    class SimpleObject:
        def __init__(self) -> None:
            self.data = "ok"

    payload = {
        "uuid": sample_uuid,
        "datetime": sample_datetime,
        "date": sample_date,
        "time": sample_time,
        "decimal": Decimal("1.23"),
        "pydantic_like": DummyModel(42),
        "object_with_dict": SimpleObject(),
    }

    encoded = json_dumps(payload)

    assert str(sample_uuid) in encoded
    assert sample_datetime.isoformat() in encoded
    assert sample_date.isoformat() in encoded
    assert sample_time.isoformat() in encoded
    assert "1.23" in encoded
    assert '"value": 42' in encoded
    assert '"data": "ok"' in encoded


def test_json_dumps_raises_for_unsupported_types():
    class NonSerializable:
        def __init__(self) -> None:
            self.data = {1, 2, 3}

    with pytest.raises(TypeError):
        json_dumps(NonSerializable())
