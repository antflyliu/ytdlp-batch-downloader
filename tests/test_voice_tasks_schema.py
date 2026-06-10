from __future__ import annotations

from pathlib import Path


def test_voice_tasks_schema_bootstraps_and_round_trips(monkeypatch, tmp_path):
    import monitor.db as db

    db_path = tmp_path / "voice-tasks.db"
    data_dir = tmp_path / "data"
    monkeypatch.setattr(db, "_DB_PATH", str(db_path))
    monkeypatch.setattr(db, "_DATA_DIR", str(data_dir))
    monkeypatch.setattr(db, "_SCHEMA_PATH", str(Path(__file__).resolve().parents[1] / "monitor" / "schema.sql"))

    db.init_db()
    task_id = db.create_voice_task(
        kind="synthesis",
        provider="silent",
        capability="speech_synthesis",
        source="manual_voice",
        input_text_hash="sha256:" + "a" * 64,
        options={"text": "hello"},
    )
    db.update_voice_task(
        task_id,
        status="done",
        progress=100,
        output_audio_path=str(tmp_path / "voice.wav"),
        result={"provider": "silent"},
    )

    task = db.get_voice_task(task_id)
    tasks, total = db.list_voice_tasks(kind="synthesis")

    assert total == 1
    assert tasks[0]["task_id"] == task_id
    assert task["status"] == "done"
    assert task["progress"] == 100
    assert task["options"] == {"text": "hello"}
    assert task["result"] == {"provider": "silent"}
    assert task["cancel_requested"] is False


def test_voice_task_cancel_marks_pending_task_finished(monkeypatch, tmp_path):
    import monitor.db as db

    db_path = tmp_path / "voice-tasks.db"
    data_dir = tmp_path / "data"
    monkeypatch.setattr(db, "_DB_PATH", str(db_path))
    monkeypatch.setattr(db, "_DATA_DIR", str(data_dir))
    monkeypatch.setattr(db, "_SCHEMA_PATH", str(Path(__file__).resolve().parents[1] / "monitor" / "schema.sql"))

    db.init_db()
    task_id = db.create_voice_task(
        kind="synthesis",
        provider="silent",
        capability="speech_synthesis",
        source="manual_voice",
        input_text_hash="sha256:" + "b" * 64,
        options={},
    )

    task = db.request_cancel_voice_task(task_id, "stop")

    assert task["status"] == "cancelled"
    assert task["cancel_requested"] is True
    assert task["cancel_message"] == "stop"
    assert task["finished_at"]
