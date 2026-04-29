import logging


def test_safe_rotating_handler_keeps_logging_when_rollover_file_is_locked(monkeypatch, tmp_path, capsys):
    from logging_config import WindowsSafeRotatingFileHandler

    log_file = tmp_path / "ytdl.log"
    log_file.write_text("x" * 128, encoding="utf-8")

    handler = WindowsSafeRotatingFileHandler(
        log_file,
        maxBytes=1,
        backupCount=1,
        encoding="utf-8",
    )
    monkeypatch.setattr(handler, "shouldRollover", lambda record: True)
    monkeypatch.setattr(
        handler,
        "doRollover",
        lambda: (_ for _ in ()).throw(PermissionError(32, "locked")),
    )

    logger = logging.getLogger("test.windows.locked.rollover")
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)

    logger.info("scan continues after locked rollover")
    handler.close()
    logger.handlers.clear()

    assert "scan continues after locked rollover" in log_file.read_text(encoding="utf-8")
    assert "Logging error" not in capsys.readouterr().err


def test_get_logger_reuses_one_file_handler_for_all_named_loggers(monkeypatch, tmp_path):
    import logging_config

    log_file = tmp_path / "ytdl.log"
    monkeypatch.setattr(logging_config, "_LOG_FILE", log_file)
    monkeypatch.setattr(logging_config, "_shared_file_handler", None, raising=False)

    logger_a = logging.getLogger("test.shared.logger.a")
    logger_b = logging.getLogger("test.shared.logger.b")
    logger_a.handlers.clear()
    logger_b.handlers.clear()

    configured_a = logging_config.get_logger("test.shared.logger.a")
    configured_b = logging_config.get_logger("test.shared.logger.b")

    try:
        assert configured_a.handlers
        assert configured_b.handlers
        assert configured_a.handlers[0] is configured_b.handlers[0]
    finally:
        seen = set()
        for logger in (configured_a, configured_b):
            for handler in list(logger.handlers):
                logger.removeHandler(handler)
                if id(handler) not in seen:
                    seen.add(id(handler))
                    handler.close()
        logging_config._shared_file_handler = None
