import json
import pytest
from pathlib import Path
from research_team.orchestrator.coordinator import ResearchCoordinator


def _make_manifest(tmp_path: Path, session_name: str, run_id: int, topic: str) -> Path:
    artifacts = tmp_path / "sessions" / session_name / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    manifest = artifacts / f"manifest_run{run_id}.json"
    manifest.write_text(json.dumps({
        "run_id": run_id,
        "topic": topic,
        "style": "research_report",
        "report_path": "",
    }), encoding="utf-8")
    return manifest


def _make_coordinator(tmp_path: Path) -> ResearchCoordinator:
    coord = ResearchCoordinator.__new__(ResearchCoordinator)
    coord._workspace_dir = str(tmp_path)
    return coord


def test_list_completed_sessions_returns_all_runs(tmp_path):
    """同一フォルダー内の複数 run が全件返される（重複排除なし）"""
    _make_manifest(tmp_path, "20260425_テーマA", 1, "テーマA")
    _make_manifest(tmp_path, "20260425_テーマA", 2, "テーマB")

    coord = _make_coordinator(tmp_path)
    sessions = coord.list_completed_sessions()

    assert len(sessions) == 2
    topics = {s.topic for s in sessions}
    assert topics == {"テーマA", "テーマB"}


def test_list_completed_sessions_run_key_format(tmp_path):
    """run_key が '{session_id}::run{run_id}' 形式で設定される"""
    _make_manifest(tmp_path, "20260425_テーマA", 1, "テーマA")

    coord = _make_coordinator(tmp_path)
    sessions = coord.list_completed_sessions()

    assert len(sessions) == 1
    assert sessions[0].run_key == "20260425_テーマA::run1"


def test_list_sessions_for_ui_includes_run_key(tmp_path):
    """_list_sessions_for_ui の各エントリに run_key が含まれる"""
    _make_manifest(tmp_path, "20260425_テーマA", 1, "テーマA")
    _make_manifest(tmp_path, "20260425_テーマA", 2, "テーマB")

    coord = _make_coordinator(tmp_path)
    ui_list = coord._list_sessions_for_ui()

    assert len(ui_list) == 2
    run_keys = {e["run_key"] for e in ui_list}
    assert "20260425_テーマA::run1" in run_keys
    assert "20260425_テーマA::run2" in run_keys


def test_list_completed_sessions_different_folders(tmp_path):
    """異なるフォルダーの run も全件返される"""
    _make_manifest(tmp_path, "20260425_フォルダA", 1, "テーマA")
    _make_manifest(tmp_path, "20260425_フォルダB", 1, "テーマB")

    coord = _make_coordinator(tmp_path)
    sessions = coord.list_completed_sessions()

    assert len(sessions) == 2
