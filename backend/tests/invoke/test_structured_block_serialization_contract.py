import json
from pathlib import Path

from app.features.invoke.stream_payloads import serialize_stream_data_value

_SERIALIZATION_CASES = json.loads(
    (
        Path(__file__).resolve().parents[3]
        / "docs/contracts/structured-block-stable-serialization-cases.json"
    ).read_text(encoding="utf-8")
)


def test_serialize_stream_data_value_matches_shared_contract_cases() -> None:
    for case in _SERIALIZATION_CASES:
        assert serialize_stream_data_value(case["value"]) == case["expected"]
