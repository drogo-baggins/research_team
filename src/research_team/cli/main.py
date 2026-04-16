import asyncio
import logging
import os
import traceback
from typing import Optional
import typer
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

app = typer.Typer(help="Research Team Agent System")


@app.command("start")
def start(
    depth: str = typer.Option("standard", help="調査の深さ: quick|standard|deep"),
    search_mode: Optional[str] = typer.Option(None, help="検索モード: human|tavily|serper"),
    workspace: Optional[str] = typer.Option(None, help="作業ディレクトリ"),
    output_format: str = typer.Option("markdown", help="出力形式: markdown|pdf|excel"),
):
    """ブラウザ制御パネルを起動してリサーチを開始する"""
    import os
    if search_mode:
        os.environ["SEARCH_MODE"] = search_mode

    from research_team.orchestrator.coordinator import ResearchCoordinator
    from research_team.ui.control_ui import ControlUI
    from playwright.async_api import async_playwright

    async def _run():
        log_path = os.path.join(os.getcwd(), "rt_run.log")
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(asctime)s %(name)s %(levelname)s %(message)s",
            handlers=[
                logging.FileHandler(log_path, encoding="utf-8"),
                logging.StreamHandler(),
            ],
        )
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=False)
            ui = ControlUI(browser)
            await ui.start()

            await ui.append_log("running", "システム起動中...")
            await ui.append_agent_message("System", "Research Team が起動しました。")

            coordinator = ResearchCoordinator(workspace_dir=workspace, ui=ui)
            try:
                await coordinator.run_interactive(depth=depth, output_format=output_format)
            except Exception as exc:
                tb = traceback.format_exc()
                logger.error("fatal error:\n%s", tb)
                await ui.append_agent_message("System", f"致命的エラー: {exc}")
                await ui.append_log("running", tb)
                typer.echo(f"Error: {exc}\n{tb}", err=True)
                raise

            await ui.wait_until_closed()

    asyncio.run(_run())


project_app = typer.Typer(help="プロジェクト管理コマンド")
app.add_typer(project_app, name="project")


@project_app.command("init")
def project_init(
    topic: str = typer.Argument(..., help="調査テーマ"),
    workspace: Optional[str] = typer.Option(None, help="作業ディレクトリ"),
):
    """新しいプロジェクトを作成してアクティブにする"""
    from research_team.project.manager import ProjectManager
    mgr = ProjectManager(workspace_dir=workspace)
    project = mgr.init(topic)
    mgr.switch(project.id)
    typer.echo(f"✅ プロジェクト作成: {project.id}")
    typer.echo(f"   テーマ: {project.topic}")
    typer.echo(f"   作業フォルダ: {mgr.project_files_dir(project.id)}")


@project_app.command("list")
def project_list(
    workspace: Optional[str] = typer.Option(None, help="作業ディレクトリ"),
):
    """プロジェクト一覧を表示する"""
    from research_team.project.manager import ProjectManager
    mgr = ProjectManager(workspace_dir=workspace)
    projects = mgr.list_projects()
    active_id = mgr.get_active_id()
    if not projects:
        typer.echo("プロジェクトがありません。")
        return
    for p in projects:
        marker = "▶" if p.id == active_id else " "
        status = "[archived]" if p.status.value == "archived" else ""
        typer.echo(f"{marker} {p.id[:8]}  {p.topic}  {status}")


@project_app.command("switch")
def project_switch(
    project_id: str = typer.Argument(..., help="プロジェクトID（前方一致可）"),
    workspace: Optional[str] = typer.Option(None, help="作業ディレクトリ"),
):
    """アクティブプロジェクトを切り替える"""
    from research_team.project.manager import ProjectManager
    mgr = ProjectManager(workspace_dir=workspace)
    projects = mgr.list_projects()
    matched = [p for p in projects if p.id.startswith(project_id)]
    if not matched:
        typer.echo(f"❌ プロジェクトが見つかりません: {project_id}", err=True)
        raise typer.Exit(1)
    if len(matched) > 1:
        typer.echo(f"❌ 複数のプロジェクトが一致します。IDをより長く指定してください。", err=True)
        raise typer.Exit(1)
    project = mgr.switch(matched[0].id)
    typer.echo(f"✅ 切り替え完了: {project.topic}")
    typer.echo(f"   ID: {project.id}")


@project_app.command("archive")
def project_archive(
    project_id: str = typer.Argument(..., help="プロジェクトID（前方一致可）"),
    workspace: Optional[str] = typer.Option(None, help="作業ディレクトリ"),
):
    """プロジェクトをアーカイブする（アーカイブ済みは編集・アクティブ化不可）"""
    from research_team.project.manager import ProjectManager
    mgr = ProjectManager(workspace_dir=workspace)
    projects = mgr.list_projects()
    matched = [p for p in projects if p.id.startswith(project_id)]
    if not matched:
        typer.echo(f"❌ プロジェクトが見つかりません: {project_id}", err=True)
        raise typer.Exit(1)
    if len(matched) > 1:
        typer.echo(f"❌ 複数のプロジェクトが一致します。IDをより長く指定してください。", err=True)
        raise typer.Exit(1)
    target = matched[0]
    mgr.archive(target.id)
    if mgr.get_active_id() == target.id:
        mgr.set_active_id(None)
    typer.echo(f"✅ アーカイブ完了: {target.topic}")


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context):
    if ctx.invoked_subcommand is None:
        ctx.invoke(start)


if __name__ == "__main__":
    app()
