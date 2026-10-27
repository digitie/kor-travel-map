"""worker pair 시험 자체의 IPC·실패 회수 경계를 DB 없이 검증한다."""

from __future__ import annotations

import pickle

import pytest

from tests.integration import test_provider_snapshot_worker_pair as pair


class _Pipe:
    def __init__(self, message=None):
        self.message = message
        self.sent = []
        self.closed = False

    def send_bytes(self, data):
        self.sent.append(data)

    def recv_bytes(self, maxlength):
        encoded = pickle.dumps(self.message, protocol=5)
        assert len(encoded) <= maxlength
        return encoded

    def poll(self, seconds):
        return self.message is not None

    def close(self):
        self.closed = True


def test_oversized_request_is_rejected_before_any_pipe_write():
    pipe = _Pipe()
    with pytest.raises(ValueError, match="fixed bound"):
        pair._send(pipe, {"artifact": b"x" * pair._MESSAGE_LIMIT})
    assert pipe.sent == []


@pytest.mark.parametrize(
    ("message", "match"),
    [
        ({"stage": "error", "profile": "airport", "error_class": "RuntimeError"}, "RuntimeError"),
        ({"stage": "committed", "profile": "rest"}, None),
    ],
)
async def test_child_error_or_wrong_profile_cannot_be_accepted_as_commit(message, match):
    with pytest.raises(AssertionError, match=match):
        await pair._receive(_Pipe(message), "committed", "airport")


async def test_foreign_identity_is_not_signalled_and_second_owned_child_is_still_cleaned(
    monkeypatch,
):
    class Process:
        def __init__(self, pid):
            self.pid = pid
            self.alive = True
            self.closed = False

        def join(self, seconds):
            assert 0 <= seconds <= 15

        def is_alive(self):
            return self.alive

        def close(self):
            assert not self.alive
            self.closed = True

    workers = {"airport": Process(101), "rest": Process(102)}
    pipes = {profile: (_Pipe(), _Pipe()) for profile in workers}
    ppid = pair.os.getpid()
    identities = {"airport": (ppid, 1), "rest": (ppid, 2)}
    signalled, closed = [], []

    def identity(pid):
        return (ppid, 999) if pid == 101 else (ppid, 2)

    def kill(fd):
        signalled.append(fd)
        workers["rest"].alive = False

    monkeypatch.setattr(pair, "_process_identity", identity)
    monkeypatch.setattr(pair, "_pidfd_kill", kill)
    monkeypatch.setattr(pair.os, "close", closed.append)
    primary = RuntimeError("original failure")
    result = await pair._cleanup(workers, pipes, identities, {"airport": 11, "rest": 12}, primary)
    assert result is primary
    assert signalled == [12]
    assert closed == [11, 12]
    assert workers["rest"].closed
    assert all(pipe.closed for endpoints in pipes.values() for pipe in endpoints)
    assert primary.__notes__ == ["owned worker cleanup failed: AssertionError"]


async def test_cleanup_after_start_before_identity_or_pidfd_was_saved(monkeypatch):
    class Process:
        pid = 201
        alive = True
        closed = False

        def join(self, seconds):
            assert 0 <= seconds <= 15

        def is_alive(self):
            return self.alive

        def close(self):
            assert not self.alive
            self.closed = True

    process = Process()
    endpoints = (_Pipe(), _Pipe())
    parent = pair.os.getpid()
    opened, closed = [], []

    def open_fd(pid):
        opened.append(pid)
        return 21

    def kill(fd):
        assert fd == 21
        process.alive = False

    monkeypatch.setattr(pair, "_process_identity", lambda pid: (parent, 3))
    monkeypatch.setattr(pair, "_pidfd_open", open_fd)
    monkeypatch.setattr(pair, "_pidfd_kill", kill)
    monkeypatch.setattr(pair.os, "close", closed.append)
    primary = OSError("initial identity or pidfd failure")
    result = await pair._cleanup({"rest": process}, {"rest": endpoints}, {}, {}, primary)
    assert result is primary
    assert opened == [201]
    assert closed == [21]
    assert process.closed
    assert all(pipe.closed for pipe in endpoints)


async def test_pipe_and_pidfd_close_errors_preserve_primary_and_clean_other_child(monkeypatch):
    class Process:
        def __init__(self, pid):
            self.pid = pid
            self.closed = False

        def join(self, seconds):
            pass

        def is_alive(self):
            return False

        def close(self):
            self.closed = True

    class BrokenPipe(_Pipe):
        def close(self):
            self.closed = True
            raise OSError("owned pipe close failed")

    workers = {"airport": Process(301), "rest": Process(302)}
    pipes = {"airport": (BrokenPipe(), _Pipe()), "rest": (_Pipe(), _Pipe())}
    closed = []

    def close_fd(fd):
        closed.append(fd)
        if fd == 31:
            raise OSError("owned pidfd close failed")

    monkeypatch.setattr(pair.os, "close", close_fd)
    primary = RuntimeError("primary object")
    result = await pair._cleanup(workers, pipes, {}, {"airport": 31, "rest": 32}, primary)
    assert result is primary
    assert closed == [31, 32]
    assert all(process.closed for process in workers.values())
    assert all(pipe.closed for endpoints in pipes.values() for pipe in endpoints)
    assert primary.__notes__ == ["owned worker cleanup failed: OSError"] * 2
