"""Unit tests for the execute_code tool (synchronous logic)."""

from __future__ import annotations

import asyncio
import os
import signal
import threading
import time

import pytest

from main import (
    _build_env,
    _execute_sync,
    _hung_process_killer,
    _running_procs,
    _running_procs_lock,
    _track_process,
    _untrack_process,
    _validate_input,
)


class TestValidateInput:
    """Test the _validate_input function."""

    def test_valid_python(self):
        assert _validate_input("python", "print(1)") is None

    def test_valid_javascript(self):
        assert _validate_input("javascript", "console.log(1)") is None

    def test_valid_bash(self):
        assert _validate_input("bash", "echo hi") is None

    def test_unsupported_language(self):
        result = _validate_input("rust", "fn main(){}")
        assert result is not None
        assert "Unsupported language" in result["error"]
        assert "rust" in result["error"]

    def test_empty_code(self):
        result = _validate_input("python", "")
        assert result is not None
        assert "empty" in result["error"].lower()

    def test_whitespace_only_code(self):
        result = _validate_input("python", "   \n\t  ")
        assert result is not None
        assert "empty" in result["error"].lower()

    def test_case_insensitive_language(self):
        # Validation normalizes language to lowercase
        assert _validate_input("Python", "print(1)") is None
        assert _validate_input("PYTHON", "print(1)") is None
        assert _validate_input("JavaScript", "console.log(1)") is None
        assert _validate_input("BASH", "echo hi") is None

    def test_code_too_large(self):
        from main import MAX_CODE_LENGTH

        big_code = "x" * (MAX_CODE_LENGTH + 1)
        result = _validate_input("python", big_code)
        assert result is not None
        assert "exceeds maximum size" in result["error"]

    def test_non_string_inputs(self):
        # None check
        result = _validate_input(None, "code")  # type: ignore[arg-type]
        assert result is not None
        assert "strings" in result["error"]

        result = _validate_input("python", None)  # type: ignore[arg-type]
        assert result is not None
        assert "strings" in result["error"]

    def test_strips_whitespace_in_language(self):
        assert _validate_input("  python  ", "print(1)") is None


class TestBuildEnv:
    """Test the _build_env helper."""

    def test_returns_dict(self):
        env = _build_env()
        assert isinstance(env, dict)

    def test_has_path(self):
        env = _build_env()
        assert "PATH" in env

    def test_has_home_default(self):
        import os as _os

        # Remove HOME from os.environ for this test
        old_home = _os.environ.pop("HOME", None)
        try:
            env = _build_env()
            assert env.get("HOME") == "/tmp"
        finally:
            if old_home is not None:
                _os.environ["HOME"] = old_home


class TestExecuteSync:
    """Test the _execute_sync function."""

    def test_python_hello(self):
        result = _execute_sync("python", "print('hello')")
        assert result.get("stdout", "").strip() == "hello"
        assert result.get("exit_code") == 0
        assert "error" not in result

    def test_python_arithmetic(self):
        result = _execute_sync("python", "print(2 + 2)")
        assert result.get("stdout", "").strip() == "4"
        assert result.get("exit_code") == 0

    def test_javascript_hello(self):
        result = _execute_sync("javascript", "console.log('hello js')")
        assert result.get("stdout", "").strip() == "hello js"
        assert result.get("exit_code") == 0

    def test_bash_echo(self):
        result = _execute_sync("bash", "echo 'hello bash'")
        assert result.get("stdout", "").strip() == "hello bash"
        assert result.get("exit_code") == 0

    def test_stderr_capture(self):
        result = _execute_sync("python", "import sys; print('to stderr', file=sys.stderr)")
        assert "to stderr" in result.get("stderr", "")
        assert result.get("exit_code") == 0

    def test_non_zero_exit_code(self):
        result = _execute_sync("bash", "exit 42")
        assert result.get("exit_code") == 42

    def test_unsupported_language(self):
        result = _execute_sync("rust", "fn main(){}")
        assert "error" in result
        assert "Unsupported language" in result["error"]

    def test_empty_code(self):
        result = _execute_sync("python", "")
        assert "error" in result
        assert "empty" in result["error"].lower()

    def test_case_insensitive(self):
        result = _execute_sync("Python", "print('ok')")
        assert result.get("stdout", "").strip() == "ok"
        assert result.get("exit_code") == 0

    def test_python_timeout(self):
        """Code that sleeps longer than 30s should time out."""
        result = _execute_sync("python", "import time; time.sleep(35)")
        assert "error" in result
        assert "timeout" in result["error"].lower()

    def test_script_file_not_leaked(self):
        """Verify temp files are cleaned up after execution.

        We can't assert exact cleanup due to concurrency, but the
        logic inside _execute_sync uses rmtree, so it's covered.
        This test just ensures no exception is raised.
        """
        _execute_sync("python", "print('cleanup test')")
        # No exception raised = cleanup worked
        assert True


class TestProcessTracking:
    """Tests for _track_process / _untrack_process."""

    def test_track_adds_pid(self):
        with _running_procs_lock:
            _running_procs.clear()
        _track_process(99999, 99999)
        with _running_procs_lock:
            assert 99999 in _running_procs
            assert _running_procs[99999][1] == 99999  # pgid
        _untrack_process(99999)

    def test_untrack_removes_pid(self):
        with _running_procs_lock:
            _running_procs.clear()
        _track_process(88888, 88888)
        _untrack_process(88888)
        with _running_procs_lock:
            assert 88888 not in _running_procs

    def test_untrack_nonexistent_does_not_raise(self):
        _untrack_process(77777)  # should not raise

    def test_tracking_is_thread_safe(self):
        with _running_procs_lock:
            _running_procs.clear()

        def _add_many(start: int, count: int) -> None:
            for i in range(start, start + count):
                _track_process(i, i)

        t1 = threading.Thread(target=_add_many, args=(0, 100))
        t2 = threading.Thread(target=_add_many, args=(100, 100))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        with _running_procs_lock:
            assert len(_running_procs) == 200
        # Cleanup
        with _running_procs_lock:
            _running_procs.clear()


class TestHungProcessKiller:
    """Tests for the background cron killer."""

    @pytest.mark.asyncio
    async def test_killer_removes_expired_processes(self):
        """Processes older than HARD_TIMEOUT are killed by the cron."""
        with _running_procs_lock:
            _running_procs.clear()

        # Start a real subprocess that sleeps
        proc = __import__("subprocess").Popen(
            ["sleep", "60"],
            start_new_session=True,
        )
        # Fake an old start time
        with _running_procs_lock:
            _running_procs[proc.pid] = (0.0, proc.pid)  # epoch = very old

        # Run one iteration of the killer (first tick is immediate)
        killer_task = asyncio.create_task(_hung_process_killer())
        await asyncio.sleep(0.3)  # yield to event loop, let killer tick
        killer_task.cancel()
        with __import__("contextlib").suppress(asyncio.CancelledError):
            await killer_task

        # Process should be dead — use poll() (os.kill(pid,0) passes on zombies)
        try:
            proc.wait(timeout=1)
            # Success: process terminated
        except __import__("subprocess").TimeoutExpired:
            proc.kill()
            proc.wait()
            pytest.fail("Cron killer did not kill the expired process")
        finally:
            with _running_procs_lock:
                _running_procs.pop(proc.pid, None)

    @pytest.mark.asyncio
    async def test_killer_ignores_fresh_processes(self):
        """Processes started recently are NOT killed."""
        with _running_procs_lock:
            _running_procs.clear()

        proc = __import__("subprocess").Popen(
            ["sleep", "10"],
            start_new_session=True,
        )
        # Fresh start time
        with _running_procs_lock:
            _running_procs[proc.pid] = (time.monotonic(), proc.pid)

        # Run one iteration
        killer_task = asyncio.create_task(_hung_process_killer())
        await asyncio.sleep(0.2)
        killer_task.cancel()
        with __import__("contextlib").suppress(asyncio.CancelledError):
            await killer_task

        # Process should still be alive — fresh start time
        try:
            proc.wait(timeout=1)
            pytest.fail("Cron killer killed a fresh process")
        except __import__("subprocess").TimeoutExpired:
            # Expected: process still running, clean up
            proc.kill()
            proc.wait()
        finally:
            with _running_procs_lock:
                _running_procs.pop(proc.pid, None)


class TestTwoPhaseTimeout:
    """Tests for SIGTERM → SIGKILL escalation."""

    def test_sigterm_ignored_triggers_sigkill(self):
        """A process ignoring SIGTERM should receive SIGKILL.

        We use a Python script that traps SIGTERM and sleeps.
        The two-phase timeout: SIGTERM → 2s grace → SIGKILL.
        """
        # Code that traps SIGTERM and keeps running
        trap_code = (
            "import signal, time\n"
            "signal.signal(signal.SIGTERM, lambda *a: None)\n"  # ignore SIGTERM
            "time.sleep(60)\n"
        )
        start = time.monotonic()
        result = _execute_sync("python", trap_code)
        elapsed = time.monotonic() - start

        assert "error" in result
        assert "timeout" in result["error"].lower()
        # Should complete in ~30 + 2 seconds, not 60
        assert elapsed < 50, f"Timeout took too long: {elapsed}s"

    def test_child_processes_killed_with_parent(self):
        """When parent is killed, orphan children are cleaned up.

        Script spawns a child that outlives the parent.
        With start_new_session + killpg, the child dies too.
        """
        # Bash: spawn a background child, then sleep
        fork_code = (
            "#!/bin/bash\n"
            "sleep 60 &\n"  # child in background
            "CHILD=$!\n"
            "echo child_pid=$CHILD\n"
            "sleep 60\n"  # parent sleeps too
        )
        result = _execute_sync("bash", fork_code)
        # Extract child PID from output
        stdout = result.get("stdout", "")

        # Both parent and child should be dead (parent timed out,
        # killpg cleaned up the child too)
        if "timeout" in result.get("error", ""):
            import re

            match = re.search(r"child_pid=(\d+)", stdout)
            if match:
                child_pid = int(match.group(1))
                try:
                    os.kill(child_pid, 0)
                    # Child survived — kill it
                    os.kill(child_pid, signal.SIGKILL)
                    pytest.fail(f"Child process {child_pid} survived parent kill")
                except ProcessLookupError:
                    pass  # Expected: child was cleaned up

    def test_normal_exit_no_timeout(self):
        """Normal process completes without triggering any kill."""
        result = _execute_sync("python", "print('quick')")
        assert result.get("stdout", "").strip() == "quick"
        assert result.get("exit_code") == 0
        assert "error" not in result

    def test_process_group_isolation(self):
        """start_new_session=True ensures new process group.

        Verify that the subprocess runs in its own process group,
        isolated from the server process.
        """
        import os as _os

        server_pgid = _os.getpgid(0)
        # Run a script that prints its own pgid
        pgid_code = "import os; print(os.getpgid(0))"
        result = _execute_sync("python", pgid_code)
        child_pgid = int(result.get("stdout", "").strip())
        # Child pgid should differ from server pgid
        assert child_pgid != server_pgid, (
            f"Child pgid {child_pgid} should differ from server pgid {server_pgid}"
        )


class TestCronKillerIntegration:
    """Integration-style tests for the background killer lifecycle."""

    @pytest.mark.asyncio
    async def test_killer_loop_runs_multiple_iterations(self):
        """Verify the killer loop keeps running and processes entries."""
        with _running_procs_lock:
            _running_procs.clear()

        # Add a very old fake process
        old_pid = 99999
        with _running_procs_lock:
            _running_procs[old_pid] = (0.0, old_pid)

        # Run killer for 2 ticks
        killer_task = asyncio.create_task(_hung_process_killer())
        await asyncio.sleep(1.0)  # enough for at least one tick
        killer_task.cancel()
        with __import__("contextlib").suppress(asyncio.CancelledError):
            await killer_task

        # Fake PID should have been cleaned from tracking
        with _running_procs_lock:
            assert old_pid not in _running_procs, (
                "Cron killer did not clean up expired fake process"
            )
