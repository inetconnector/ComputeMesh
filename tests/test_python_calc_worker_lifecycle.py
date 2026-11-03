"""MCP calculator process lifecycle and IPC exception policy."""

from unittest.mock import Mock, patch

import pytest

from services.mcp.builtin import python_calc


def test_spawn_failure_closes_both_pipes_without_querying_unstarted_process() -> None:
    context = Mock()
    parent = Mock()
    child = Mock()
    process = Mock()
    process.start.side_effect = OSError("spawn unavailable")
    context.Pipe.return_value = (parent, child)
    context.Process.return_value = process
    with patch.object(python_calc.multiprocessing, "get_context", return_value=context):
        result = python_calc.run_python_calc(expression="1+1")
    assert result["error"].startswith("Berechnungsprozess fehlgeschlagen: OSError: spawn unavailable")
    parent.close.assert_called_once()
    child.close.assert_called_once()
    process.is_alive.assert_not_called()
    process.terminate.assert_not_called()


def test_unexpected_spawn_programming_error_is_not_disguised_as_normal_calculation_error() -> None:
    context = Mock()
    parent = Mock()
    child = Mock()
    process = Mock()
    process.start.side_effect = AssertionError("broken process contract")
    context.Pipe.return_value = (parent, child)
    context.Process.return_value = process
    with patch.object(python_calc.multiprocessing, "get_context", return_value=context), pytest.raises(AssertionError, match="broken process contract"):
        python_calc.run_python_calc(expression="1+1")
    parent.close.assert_called_once()
    child.close.assert_called_once()


def test_worker_broken_pipe_does_not_mask_original_calculation_failure() -> None:
    connection = Mock()
    connection.send.side_effect = BrokenPipeError("parent gone")
    python_calc._worker("1 / 0", connection)
    connection.close.assert_called_once()
    # Division fails before a result can be sent; only the error report
    # reaches the already-closed pipe.
    connection.send.assert_called_once()


def test_worker_unexpected_pipe_bug_surfaces() -> None:
    connection = Mock()
    connection.send.side_effect = RuntimeError("unexpected IPC bug")
    with pytest.raises(RuntimeError, match="unexpected IPC bug"):
        python_calc._worker("1+1", connection)
    connection.close.assert_called_once()


def test_worker_expected_pipe_close_error_is_tolerated() -> None:
    connection = Mock()
    connection.close.side_effect = OSError("already closed")
    python_calc._worker("2+2", connection)
    connection.send.assert_called_once_with({"ok": True, "result": 4})
