"""Native memory locks distinguish expected OS failure from unexpected bugs."""

from unittest.mock import Mock

import pytest

from services.common import secure_memory


@pytest.mark.parametrize("operation,native_name", [
    ("lock_memory_buffer", "_mlock"),
    ("unlock_memory_buffer", "_munlock"),
])
def test_native_os_denial_fails_closed(
    monkeypatch: pytest.MonkeyPatch, operation: str, native_name: str,
) -> None:
    monkeypatch.setattr(secure_memory, "_HAS_MLOCK", True)
    monkeypatch.setattr(secure_memory, "_SYSTEM", "Linux")
    native = Mock(side_effect=OSError("native page lock denied"))
    monkeypatch.setattr(secure_memory, native_name, native, raising=False)
    assert getattr(secure_memory, operation)(bytearray(b"private bytes")) is False
    native.assert_called_once()


@pytest.mark.parametrize("operation,native_name", [
    ("lock_memory_buffer", "_mlock"),
    ("unlock_memory_buffer", "_munlock"),
])
def test_unexpected_native_programming_error_remains_visible(
    monkeypatch: pytest.MonkeyPatch, operation: str, native_name: str,
) -> None:
    monkeypatch.setattr(secure_memory, "_HAS_MLOCK", True)
    monkeypatch.setattr(secure_memory, "_SYSTEM", "Linux")
    native = Mock(side_effect=RuntimeError("unexpected native interface bug"))
    monkeypatch.setattr(secure_memory, native_name, native, raising=False)
    with pytest.raises(RuntimeError, match="unexpected native interface bug"):
        getattr(secure_memory, operation)(bytearray(b"private bytes"))


def test_invalid_memory_buffer_cannot_claim_to_be_locked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(secure_memory, "_HAS_MLOCK", True)
    assert secure_memory.lock_memory_buffer(object()) is False
