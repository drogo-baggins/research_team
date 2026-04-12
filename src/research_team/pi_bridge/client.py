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
        for ext in (".cmd", ".ps1", ""):
            candidate = shutil.which(name + ext) or shutil.which(name)
            if candidate and candidate.endswith(".cmd"):
                return [candidate]
            if candidate and candidate.endswith(".ps1"):
                return ["powershell", "-NonInteractive", "-File", candidate]
        pi_cmd = shutil.which(name + ".cmd")
        if pi_cmd:
            return [pi_cmd]
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
                    self._process.stdout.readline(), timeout=120.0
                )
            except asyncio.TimeoutError:
                break

            if not line:
                break

            try:
                data = json.loads(line.decode().strip())
                event = AgentEvent(type=data.get("type", "unknown"), data=data)
                yield event
                if event.type == "agent_end":
                    break
            except json.JSONDecodeError:
                continue
