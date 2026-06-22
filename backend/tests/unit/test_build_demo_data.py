import importlib.util
import sys
from pathlib import Path


def load_build_demo_data_module():
    script_path = Path(__file__).resolve().parents[3] / "scripts" / "build_demo_data.py"
    spec = importlib.util.spec_from_file_location("build_demo_data", script_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_media_seconds_matches_spec_window():
    module = load_build_demo_data_module()

    assert 20 <= module.MEDIA_SECONDS <= 40


def test_main_returns_nonzero_when_video_generation_fails(monkeypatch, capsys, tmp_path):
    module = load_build_demo_data_module()
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    (case_dir / "brief.txt").write_text("generated\n", encoding="utf-8")
    case = type("Case", (), {"directory": "case"})()

    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "DEMO_ROOT", tmp_path)
    monkeypatch.setattr(module, "cases", lambda: [case])
    monkeypatch.setattr(module, "write_case", lambda case: ["ffmpeg unavailable; video.mp4 requires ffmpeg"])

    assert module.main() == 1
    output = capsys.readouterr().out
    assert "Errors:" in output
    assert "ffmpeg unavailable" in output
