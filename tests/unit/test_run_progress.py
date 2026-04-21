import pytest
from pathlib import Path
from research_team.output.run_progress import RunProgress, SpecialistProgress, FILENAME


def _make_progress(tmp_path: Path) -> RunProgress:
    return RunProgress(
        run_id=1,
        topic="AIの未来",
        style="research_report",
        depth="standard",
        locales=["ja", "en"],
        all_specialists=[
            SpecialistProgress(name="AIエンジニア", expertise="AI技術"),
            SpecialistProgress(name="市場アナリスト", expertise="市場分析"),
            SpecialistProgress(name="技術ライター", expertise="技術文章"),
        ],
        wbs_artifact_path=str(tmp_path / "wbs.md"),
        created_at="2026-04-21T10:00:00",
    )


def test_run_progress_save_and_load(tmp_path):
    progress = _make_progress(tmp_path)
    path = tmp_path / FILENAME
    progress.save(path)
    loaded = RunProgress.load(path)
    assert loaded.topic == "AIの未来"
    assert loaded.run_id == 1
    assert len(loaded.all_specialists) == 3
    assert loaded.all_specialists[0].name == "AIエンジニア"


def test_run_progress_mark_specialist_done(tmp_path):
    progress = _make_progress(tmp_path)
    assert len(progress.completed_specialists) == 0
    assert len(progress.pending_specialists) == 3

    progress.mark_specialist_done("AIエンジニア", "/some/path.md")

    assert len(progress.completed_specialists) == 1
    assert progress.completed_specialists[0].name == "AIエンジニア"
    assert progress.completed_specialists[0].artifact_path == "/some/path.md"
    assert len(progress.pending_specialists) == 2


def test_run_progress_roundtrip_with_completed(tmp_path):
    progress = _make_progress(tmp_path)
    progress.mark_specialist_done("AIエンジニア", str(tmp_path / "spec_ai.md"))
    progress.mark_specialist_done("市場アナリスト", str(tmp_path / "spec_market.md"))

    path = tmp_path / FILENAME
    progress.save(path)
    loaded = RunProgress.load(path)

    assert len(loaded.completed_specialists) == 2
    assert len(loaded.pending_specialists) == 1
    assert loaded.pending_specialists[0].name == "技術ライター"


def test_artifact_writer_write_and_load_run_progress(tmp_path):
    from research_team.output.artifact_writer import ArtifactWriter

    writer = ArtifactWriter(tmp_path)
    progress = _make_progress(tmp_path)
    path = writer.write_run_progress(progress)
    assert Path(path).exists()
    assert Path(path).name == FILENAME

    loaded = writer.load_run_progress()
    assert loaded is not None
    assert loaded.topic == "AIの未来"


def test_artifact_writer_clear_run_progress(tmp_path):
    from research_team.output.artifact_writer import ArtifactWriter

    writer = ArtifactWriter(tmp_path)
    progress = _make_progress(tmp_path)
    writer.write_run_progress(progress)
    assert (tmp_path / FILENAME).exists()

    writer.clear_run_progress()
    assert not (tmp_path / FILENAME).exists()


def test_artifact_writer_load_returns_none_when_missing(tmp_path):
    from research_team.output.artifact_writer import ArtifactWriter

    writer = ArtifactWriter(tmp_path)
    result = writer.load_run_progress()
    assert result is None


def test_artifact_writer_clear_noop_when_missing(tmp_path):
    from research_team.output.artifact_writer import ArtifactWriter

    writer = ArtifactWriter(tmp_path)
    writer.clear_run_progress()


def test_run_progress_mark_unknown_specialist_is_noop(tmp_path):
    progress = _make_progress(tmp_path)
    progress.mark_specialist_done("存在しない人", "/path.md")
    assert len(progress.completed_specialists) == 0
