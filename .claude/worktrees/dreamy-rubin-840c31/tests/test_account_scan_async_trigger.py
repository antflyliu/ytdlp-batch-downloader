import threading


def test_trigger_scan_async_starts_daemon_thread_and_rejects_duplicate(monkeypatch):
    import monitor.scheduler as scheduler

    calls = []
    started_threads = []

    class FakeThread:
        def __init__(self, target, daemon=False, name=None):
            self.target = target
            self.daemon = daemon
            self.name = name
            self.started = False
            started_threads.append(self)

        def start(self):
            self.started = True

    def fake_scan(account_id, auto_download=False):
        calls.append((account_id, auto_download))

    monkeypatch.setattr(scheduler, "_manual_scan_locks", {})
    monkeypatch.setattr(scheduler, "_manual_scan_locks_guard", threading.Lock())
    monkeypatch.setattr(scheduler.threading, "Thread", FakeThread)
    monkeypatch.setattr(scheduler, "_scan_account", fake_scan)

    assert scheduler.trigger_scan_async(6, auto_download=True) is True
    assert calls == []
    assert len(started_threads) == 1
    assert started_threads[0].started is True
    assert started_threads[0].daemon is True
    assert started_threads[0].name == "manual-scan-6"

    assert scheduler.trigger_scan_async(6, auto_download=False) is False
    assert len(started_threads) == 1

    started_threads[0].target()
    assert calls == [(6, True)]

    assert scheduler.trigger_scan_async(6, auto_download=False) is True
    assert len(started_threads) == 2
    started_threads[1].target()
    assert calls == [(6, True), (6, False)]


def test_account_scan_endpoint_queues_background_scan(monkeypatch):
    import server.__main__ as server_main

    calls = []
    sent = []

    def fake_trigger_scan_async(account_id, auto_download=False):
        calls.append((account_id, auto_download))
        return True

    monkeypatch.setattr(server_main._scheduler, "trigger_scan_async", fake_trigger_scan_async)

    handler = object.__new__(server_main.MonitorHandler)
    handler._send_json = lambda data, status=200: sent.append((data, status))

    server_main.MonitorHandler._api_account_scan(
        handler,
        {"account_id": "6", "auto_download": True},
    )

    assert calls == [(6, True)]
    assert sent == [({"ok": True, "queued": True, "already_running": False}, 200)]
