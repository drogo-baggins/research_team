import json
from pathlib import Path
from research_team.output.run_manifest import RunManifest, SpecialistEntry


def test_run_manifest_save_and_load(tmp_path):
    entry = SpecialistEntry(
        name="経済アナリスト",
        expertise="経済・金融",
        artifact_path=str(tmp_path / "specialist_経済アナリスト_run1_20260420.md"),
    )
    manifest = RunManifest(
        run_id=1,
        topic="AI産業の未来",
        style="research_report",
        specialists=[entry],
        discussion_artifact_path=None,
        report_path=str(tmp_path / "report_AI産業_20260420.md"),
    )
    manifest_path = tmp_path / "manifest_run1.json"
    manifest.save(manifest_path)

    loaded = RunManifest.load(manifest_path)
    assert loaded.run_id == 1
    assert loaded.topic == "AI産業の未来"
    assert len(loaded.specialists) == 1
    assert loaded.specialists[0].name == "経済アナリスト"
    assert loaded.report_path == str(tmp_path / "report_AI産業_20260420.md")


def test_run_manifest_with_discussion(tmp_path):
    manifest = RunManifest(
        run_id=2,
        topic="テスト",
        style="magazine_column",
        specialists=[],
        discussion_artifact_path=str(tmp_path / "discussion_run2_20260420.md"),
        report_path=str(tmp_path / "report_test_20260420.md"),
    )
    manifest_path = tmp_path / "manifest_run2.json"
    manifest.save(manifest_path)
    loaded = RunManifest.load(manifest_path)
    assert loaded.discussion_artifact_path is not None
