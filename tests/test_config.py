from pathlib import Path
from sentinel.config import load_config


def test_load_config_reads_values_and_defaults(tmp_path: Path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        "stream:\n"
        "  rtsp_url: rtsp://example.local:554/stream\n"
        "  capture_fps: 8\n"
    )
    cfg = load_config(cfg_file)
    assert cfg.stream.rtsp_url == "rtsp://example.local:554/stream"
    assert cfg.stream.capture_fps == 8
    # defaults
    assert cfg.stream.pose_downscale_width == 960
    assert cfg.thresholds.forward_head_margin_deg == 12.0
    assert cfg.server.port == 8088
    assert cfg.db_path == "~/.desk-sentinel/desk_sentinel.db"


def test_nudge_config_defaults(tmp_path):
    from sentinel.config import load_config
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        "stream:\n"
        "  rtsp_url: rtsp://x/y\n"
    )
    cfg = load_config(cfg_file)
    assert cfg.nudges.break_after_seconds == 3600
    assert cfg.nudges.poor_posture_seconds == 300
    assert cfg.nudges.work_start_hour == 8.5
    assert cfg.nudges.work_end_hour == 17.5
    assert cfg.nudges.speak_volume == 50
    assert cfg.nudges.enabled is True
    assert cfg.nudges.cooldown_seconds["break_due"] == 600
    assert cfg.nudges.morning_brief.enabled is True
    assert cfg.nudges.morning_brief.after_hour == 5.0
    assert cfg.nudges.morning_brief.headline_count == 2
    assert cfg.nudges.wind_down.enabled is True
    assert cfg.nudges.wind_down.lead_minutes == 30


def test_presence_config_defaults(tmp_path):
    from sentinel.config import load_config
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        "stream:\n"
        "  rtsp_url: rtsp://x/y\n"
    )
    cfg = load_config(cfg_file)
    assert cfg.presence.work_start_hour == 8.5
    assert cfg.presence.work_end_hour == 17.5
    assert cfg.presence.gap_merge_seconds == 20
    assert cfg.presence.min_session_seconds == 30
    assert cfg.presence.trend_days == 14
    assert cfg.presence.history_days == 30


def test_presence_config_from_yaml(tmp_path):
    from sentinel.config import load_config
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        "stream:\n"
        "  rtsp_url: rtsp://x/y\n"
        "presence:\n"
        "  work_start_hour: 8\n"
        "  work_end_hour: 18\n"
        "  trend_days: 7\n"
        "  history_days: 60\n"
    )
    cfg = load_config(cfg_file)
    assert cfg.presence.work_start_hour == 8
    assert cfg.presence.work_end_hour == 18
    assert cfg.presence.trend_days == 7
    assert cfg.presence.history_days == 60
    # defaults for unspecified fields
    assert cfg.presence.gap_merge_seconds == 20
    assert cfg.presence.min_session_seconds == 30


def test_voice_config_defaults(tmp_path):
    from sentinel.config import load_config
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        "stream:\n"
        "  rtsp_url: rtsp://x/y\n"
    )
    cfg = load_config(cfg_file)
    assert cfg.voice.hotkey == "<cmd>+<alt>+d"
    assert cfg.voice.whisper_model == "base.en"
    assert cfg.voice.ollama_model == "llama3.1:8b"
    assert cfg.voice.ollama_url == "http://localhost:11434"
    assert cfg.voice.max_record_seconds == 15.0
    assert cfg.voice.silence_timeout == 1.2


def test_voice_config_from_yaml(tmp_path):
    from sentinel.config import load_config
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        "stream:\n"
        "  rtsp_url: rtsp://x/y\n"
        "voice:\n"
        "  hotkey: '<ctrl>+<alt>+v'\n"
        "  whisper_model: 'small.en'\n"
        "  ollama_model: 'llama3.2:3b'\n"
        "  max_record_seconds: 30\n"
        "  silence_timeout: 2.0\n"
    )
    cfg = load_config(cfg_file)
    assert cfg.voice.hotkey == "<ctrl>+<alt>+v"
    assert cfg.voice.whisper_model == "small.en"
    assert cfg.voice.ollama_model == "llama3.2:3b"
    assert cfg.voice.max_record_seconds == 30.0
    assert cfg.voice.silence_timeout == 2.0


def test_backup_config_defaults(tmp_path):
    from sentinel.config import load_config
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        "stream:\n"
        "  rtsp_url: rtsp://x/y\n"
    )
    cfg = load_config(cfg_file)
    assert cfg.backup.enabled is True
    assert cfg.backup.dest_dir == "~/desk-sentinel-backups"
    assert cfg.backup.keep == 14
    assert cfg.backup.interval_hours == 24.0


def test_backup_config_from_yaml(tmp_path):
    from sentinel.config import load_config
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        "stream:\n"
        "  rtsp_url: rtsp://x/y\n"
        "backup:\n"
        "  enabled: false\n"
        "  dest_dir: /tmp/mybackups\n"
        "  keep: 7\n"
        "  interval_hours: 12\n"
    )
    cfg = load_config(cfg_file)
    assert cfg.backup.enabled is False
    assert cfg.backup.dest_dir == "/tmp/mybackups"
    assert cfg.backup.keep == 7
    assert cfg.backup.interval_hours == 12.0


def test_db_path_default_is_home_relative(tmp_path):
    from sentinel.config import load_config
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        "stream:\n"
        "  rtsp_url: rtsp://x/y\n"
    )
    cfg = load_config(cfg_file)
    assert "~/.desk-sentinel" in cfg.db_path
    assert cfg.db_path.startswith("~")
