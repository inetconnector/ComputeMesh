"""Partial or malformed JSONL gateway API-key registries fail closed."""

import pytest

from services.gateway.auth import GatewayCredentialStoreError, _load_api_key_store


def test_valid_jsonl_api_key_records_load(tmp_path) -> None:
    file = tmp_path / "api-keys.jsonl"
    file.write_text(
        '{"api_key":"cm_demo_token_1234","account_id":"one"}\n'
        '{"token":"cm_demo_token_5678","account_id":"two"}\n',
        encoding="utf-8",
    )
    assert _load_api_key_store(file) == {
        "cm_demo_token_1234": "one", "cm_demo_token_5678": "two",
    }


@pytest.mark.parametrize("bad_line", ["{bad json", "null", "[]", '"string"'])
def test_one_invalid_line_rejects_entire_key_registry(tmp_path, bad_line: str) -> None:
    file = tmp_path / "api-keys.jsonl"
    file.write_text(
        '{"api_key":"cm_valid_token_1234","account_id":"owner"}\n'
        + bad_line + "\n",
        encoding="utf-8",
    )
    with pytest.raises(GatewayCredentialStoreError, match="JSONL"):
        _load_api_key_store(file)


def test_blank_jsonl_lines_are_allowed(tmp_path) -> None:
    file = tmp_path / "api-keys.jsonl"
    file.write_text(
        '\n{"token":"cm_valid_token_1234","account_id":"owner"}\n\n',
        encoding="utf-8",
    )
    assert _load_api_key_store(file) == {"cm_valid_token_1234": "owner"}
