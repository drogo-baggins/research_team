from pathlib import Path
from research_team.output.artifact_reconstructor import ArtifactReconstructor
from research_team.output.run_manifest import RunManifest, SpecialistEntry


def _write_specialist_file(path: Path, specialist_name: str, content: str) -> None:
    header = f"# 調査中間成果物 — {specialist_name} / Run 1 (20260420)\n\n"
    path.write_text(header + content, encoding="utf-8")


def test_reconstruct_combined_content_basic(tmp_path):
    path_a = tmp_path / "specialist_経済アナリスト_run1_20260420.md"
    path_b = tmp_path / "specialist_技術者_run1_20260420.md"
    _write_specialist_file(path_a, "経済アナリスト", "## 経済アナリスト\n\n経済の分析内容")
    _write_specialist_file(path_b, "技術者", "## 技術者\n\n技術の分析内容")

    manifest = RunManifest(
        run_id=1,
        topic="テスト",
        style="research_report",
        specialists=[
            SpecialistEntry("経済アナリスト", "経済・金融", str(path_a)),
            SpecialistEntry("技術者", "AI・機械学習", str(path_b)),
        ],
        discussion_artifact_path=None,
        report_path=str(tmp_path / "report.md"),
    )

    reconstructor = ArtifactReconstructor()
    combined = reconstructor.reconstruct(manifest)

    assert "経済の分析内容" in combined
    assert "技術の分析内容" in combined
    assert combined.index("経済の分析内容") < combined.index("技術の分析内容")


def test_reconstruct_includes_discussion(tmp_path):
    path_a = tmp_path / "specialist_経済アナリスト_run1_20260420.md"
    _write_specialist_file(path_a, "経済アナリスト", "経済の内容")
    disc_path = tmp_path / "discussion_run1_20260420.md"
    disc_path.write_text("# 対談\n\n対談の内容", encoding="utf-8")

    manifest = RunManifest(
        run_id=1,
        topic="テスト",
        style="magazine_column",
        specialists=[SpecialistEntry("経済アナリスト", "経済・金融", str(path_a))],
        discussion_artifact_path=str(disc_path),
        report_path=str(tmp_path / "report.md"),
    )

    reconstructor = ArtifactReconstructor()
    combined = reconstructor.reconstruct(manifest)

    assert "経済の内容" in combined
    assert "対談の内容" in combined


def test_reconstruct_missing_artifact_raises(tmp_path):
    import pytest
    manifest = RunManifest(
        run_id=1,
        topic="テスト",
        style="research_report",
        specialists=[
            SpecialistEntry("経済アナリスト", "経済・金融", str(tmp_path / "nonexistent.md")),
        ],
        discussion_artifact_path=None,
        report_path=str(tmp_path / "report.md"),
    )
    reconstructor = ArtifactReconstructor()
    with pytest.raises(FileNotFoundError, match="nonexistent.md"):
        reconstructor.reconstruct(manifest)
