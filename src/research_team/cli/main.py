import asyncio
from typing import Optional
import typer

app = typer.Typer(help="Research Team Agent System")


@app.command()
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
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=False)
            ui = ControlUI(browser)
            await ui.start()

            await ui.append_log("running", "システム起動中...")
            await ui.append_agent_message("System", "Research Team が起動しました。")

            coordinator = ResearchCoordinator(workspace_dir=workspace, ui=ui)
            await coordinator.run_interactive(depth=depth, output_format=output_format)

    asyncio.run(_run())


if __name__ == "__main__":
    app()
