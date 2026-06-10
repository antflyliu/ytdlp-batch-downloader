from __future__ import annotations

from pathlib import Path

from monitor.voice.schemas import SpeechSynthesisResult


def _handler_with_sender(server_main):
    sent = []
    handler = object.__new__(server_main.MonitorHandler)
    handler._send_json = lambda data, status=200: sent.append((data, status))
    return handler, sent


def test_voice_task_manager_runs_synthesis_with_fake_provider(monkeypatch, tmp_path):
    import monitor.db as db
    from monitor.voice import tasks as voice_tasks

    db_path = tmp_path / "voice-task-manager.db"
    monkeypatch.setattr(db, "_DB_PATH", str(db_path))
    monkeypatch.setattr(db, "_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(db, "_SCHEMA_PATH", str(Path(__file__).resolve().parents[1] / "monitor" / "schema.sql"))
    db.init_db()

    def fake_synthesize(request, cfg):
        audio_path = request.output_dir / "narration.wav"
        audio_path.write_bytes(b"wav-audio")
        metadata_path = request.output_dir / "metadata.json"
        metadata_path.write_text("{}", encoding="utf-8")
        return SpeechSynthesisResult(
            provider=request.provider or "silent",
            path=audio_path,
            mime_type="audio/wav",
            metadata_path=metadata_path,
        )

    monkeypatch.setattr(voice_tasks, "synthesize_speech", fake_synthesize)
    manager = voice_tasks.VoiceTaskManager()
    task_id = manager.create_synthesis_task(
        {"text": "hello", "provider": "silent"},
        {"voice_output_dir": str(tmp_path / "voice")},
    )

    manager.run_task(task_id, {"voice_output_dir": str(tmp_path / "voice")})

    task = db.get_voice_task(task_id)
    assert task["status"] == "done"
    assert task["progress"] == 100
    assert Path(task["output_audio_path"]).read_bytes() == b"wav-audio"
    assert task["result"]["provider"] == "silent"


def test_voice_synthesis_task_api_creates_task(monkeypatch, tmp_path):
    import server.__main__ as server_main

    handler, sent = _handler_with_sender(server_main)
    monkeypatch.setattr(server_main._db, "load_config", lambda: {"voice_output_dir": str(tmp_path / "voice")})
    monkeypatch.setattr(server_main._voice_task_mgr, "create_synthesis_task", lambda body, cfg: "voice_123")
    monkeypatch.setattr(server_main._voice_task_mgr, "start_background", lambda task_id, cfg: None)

    server_main.MonitorHandler._api_voice_synthesis_task_create(handler, {"text": "hello", "provider": "silent"})

    assert sent[-1] == ({"ok": True, "task_id": "voice_123"}, 202)


def test_voice_tasks_api_lists_and_gets_tasks(monkeypatch):
    import server.__main__ as server_main

    handler, sent = _handler_with_sender(server_main)
    handler.path = "/api/voice/tasks?kind=synthesis&limit=5&offset=0"
    monkeypatch.setattr(server_main._db, "list_voice_tasks", lambda **kwargs: ([{"task_id": "voice_1"}], 1))

    server_main.MonitorHandler._api_voice_tasks_list(handler)

    assert sent[-1][0] == {"tasks": [{"task_id": "voice_1"}], "total": 1, "limit": 5, "offset": 0}

    handler, sent = _handler_with_sender(server_main)
    monkeypatch.setattr(server_main._db, "get_voice_task", lambda task_id: {"task_id": task_id})
    server_main.MonitorHandler._api_voice_task_get(handler, "voice_1")
    assert sent[-1][0] == {"task_id": "voice_1"}


def test_voice_task_cancel_api_delegates_to_db(monkeypatch):
    import server.__main__ as server_main

    handler, sent = _handler_with_sender(server_main)
    monkeypatch.setattr(server_main._db, "request_cancel_voice_task", lambda task_id: {"task_id": task_id, "status": "cancelled"})

    server_main.MonitorHandler._api_voice_task_cancel(handler, "voice_1")

    assert sent[-1] == ({"ok": True, "task": {"task_id": "voice_1", "status": "cancelled"}}, 200)


def test_voice_file_api_rejects_paths_outside_voice_output_dir(monkeypatch, tmp_path):
    import server.__main__ as server_main

    handler, sent = _handler_with_sender(server_main)
    handler.path = f"/api/voice/file?path={tmp_path.parent / 'outside.wav'}"
    monkeypatch.setattr(server_main._db, "load_config", lambda: {"voice_output_dir": str(tmp_path / "voice")})

    server_main.MonitorHandler._api_voice_file(handler)

    assert sent[-1][1] == 400
