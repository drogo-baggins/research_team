import asyncio
import json
import os
import shutil
import sys
import uuid
from collections.abc import AsyncIterator
from research_team.pi_bridge.types import PromptRequest, AgentEvent


def _resolve_pi_bin(name: str) -> list[str]:
    if sys.platform == "win32":
        cmd_path = shutil.which(name + ".cmd")
        if cmd_path:
            bin_dir = os.path.dirname(cmd_path)
            node_exe = os.path.join(bin_dir, "node.exe")
            cli_candidates = [
                os.path.join(bin_dir, "node_modules", "@mariozechner", "pi-coding-agent", "dist", "cli.js"),
            ]
            for cli_js in cli_candidates:
                if os.path.exists(cli_js):
                    node = node_exe if os.path.exists(node_exe) else "node"
                    return [node, cli_js]
        ps1_path = shutil.which(name + ".ps1")
        if ps1_path:
            return ["powershell", "-NonInteractive", "-File", ps1_path]
    return [name]


class PiAgentClient:
    def __init__(
        self,
        system_prompt: str = "",
        model: str | None = None,
        pi_bin: str | None = None,
        workspace_dir: str | None = None,
    ):
        self._system_prompt = system_prompt
        self._model = model or os.environ.get("PI_MODEL", "github-copilot/claude-sonnet-4.5")
        self._pi_cmd = _resolve_pi_bin(pi_bin or os.environ.get("PI_AGENT_BIN", "pi"))
        self._workspace_dir = workspace_dir or os.path.join(os.getcwd(), "workspace")
        self._process: asyncio.subprocess.Process | None = None

    async def start(self) -> None:
        cmd = [*self._pi_cmd, "--mode", "rpc", "--model", self._model, "--no-session"]
        if self._system_prompt:
            cmd += ["--system-prompt", self._system_prompt]
        self._process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self._workspace_dir,
        )

    async def stop(self) -> None:
        if self._process and self._process.returncode is None:
            self._process.terminate()
            await self._process.wait()

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, *args):
        await self.stop()

    async def _send(self, req: PromptRequest) -> None:
        if not self._process or not self._process.stdin:
            raise RuntimeError("pi-agent process not started")
        line = req.model_dump_json() + "\n"
        self._process.stdin.write(line.encode())
        await self._process.stdin.drain()

    async def prompt(self, message: str) -> AsyncIterator[AgentEvent]:
        req_id = uuid.uuid4().hex
        req = PromptRequest(id=req_id, message=message)
        await self._send(req)
        async for event in self._read_events(req_id):
            yield event

    async def _read_events(self, req_id: str) -> AsyncIterator[AgentEvent]:
        if not self._process or not self._process.stdout:
            return

        while True:
            try:
                line = await asyncio.wait_for(
                    self._process.stdout.readline(), timeout=300.0
                )
            except asyncio.TimeoutError:
                break

            if not line:
                break

            raw = line.decode().strip()
            if not raw:
                continue

            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue

            event_type = data.get("type", "unknown")
            if event_type == "response":
                continue

            event = AgentEvent(type=event_type, data=data)
            yield event
            if event_type == "agent_end":
                break
