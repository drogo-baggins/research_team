import asyncio
import json
import logging
import os
import shutil
import sys
import uuid
from pathlib import Path
from collections.abc import AsyncIterator
from research_team.pi_bridge.types import PromptRequest, AgentEvent

logger = logging.getLogger(__name__)


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


_EXT_PATH = Path(__file__).parent / "web_search.ts"


class PiAgentClient:
    def __init__(
        self,
        system_prompt: str = "",
        model: str | None = None,
        pi_bin: str | None = None,
        workspace_dir: str | None = None,
        search_port: int = 0,
    ):
        self._system_prompt = system_prompt
        self._model = model or os.environ.get("PI_MODEL", "github-copilot/claude-sonnet-4.5")
        self._pi_cmd = _resolve_pi_bin(pi_bin or os.environ.get("PI_AGENT_BIN", "pi"))
        self._workspace_dir = workspace_dir or os.path.join(os.getcwd(), "workspace")
        self._search_port = search_port
        self._process: asyncio.subprocess.Process | None = None

    async def start(self) -> None:
        cmd = [*self._pi_cmd, "--mode", "rpc", "--model", self._model, "--no-session"]
        if self._system_prompt:
            cmd += ["--system-prompt", self._system_prompt]
        if _EXT_PATH.exists() and self._search_port:
            cmd += ["--extension", str(_EXT_PATH)]

        env = {**os.environ, "RT_SEARCH_PORT": str(self._search_port)}
        logger.debug("pi-agent cmd: %s", cmd)
        self._process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self._workspace_dir,
            env=env,
            limit=256 * 1024 * 1024,
        )
        await asyncio.sleep(0)
        if self._process.returncode is not None:
            assert self._process.stderr is not None
            stderr_bytes = await self._process.stderr.read()
            stderr_text = stderr_bytes.decode(errors="replace").strip()
            raise RuntimeError(
                f"pi-agent process exited immediately (rc={self._process.returncode}): {stderr_text}"
            )

    async def stop(self) -> None:
        if self._process and self._process.returncode is None:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning("pi-agent process did not terminate within 5s, killing")
                self._process.kill()
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

    async def _readline_unlimited(self, stream: asyncio.StreamReader) -> bytes:
        chunks: list[bytes] = []
        while True:
            try:
                chunks.append(await stream.readuntil(b"\n"))
                return b"".join(chunks)
            except asyncio.LimitOverrunError as exc:
                chunks.append(await stream.readexactly(exc.consumed))
            except asyncio.IncompleteReadError as exc:
                chunks.append(exc.partial)
                return b"".join(chunks)

    async def _read_events(self, req_id: str) -> AsyncIterator[AgentEvent]:
        if not self._process or not self._process.stdout:
            raise RuntimeError("pi-agent process not started")

        stderr_chunks: list[bytes] = []

        async def _drain_stderr() -> None:
            try:
                assert self._process and self._process.stderr
                async for chunk in self._process.stderr:
                    stderr_chunks.append(chunk)
            except Exception as exc:
                logger.warning("_drain_stderr: error while reading stderr: %s", exc)

        stderr_task = asyncio.create_task(_drain_stderr())

        try:
            while True:
                read_task = asyncio.create_task(
                    self._readline_unlimited(self._process.stdout)
                )
                done, _ = await asyncio.wait(
                    {read_task, stderr_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )

                if read_task in done:
                    try:
                        line = read_task.result()
                    except Exception as exc:
                        logger.error("_read_events: read_task raised: %s", exc)
                        line = b""
                else:
                    read_task.cancel()
                    try:
                        await read_task
                    except (asyncio.CancelledError, Exception):
                        pass
                    line = b""

                if not line:
                    rc = self._process.returncode
                    if rc is None:
                        await self._process.wait()
                        rc = self._process.returncode
                    stderr_text = b"".join(stderr_chunks).decode(errors="replace").strip()
                    if stderr_text:
                        logger.error("pi-agent stderr: %s", stderr_text)
                    raise RuntimeError(
                        f"pi-agent process ended unexpectedly (rc={rc}). stderr: {stderr_text}"
                    )

                raw = line.decode().strip()
                if not raw:
                    continue

                try:
                    data = json.loads(raw)
                except json.JSONDecodeError as exc:
                    logger.error("pi-agent invalid JSON line %r: %s", raw, exc)
                    raise RuntimeError(f"pi-agent sent invalid JSON: {raw!r}") from exc

                event_type = data.get("type", "unknown")
                if event_type == "response":
                    continue

                event = AgentEvent(type=event_type, data=data)
                yield event
                if event_type == "agent_end":
                    break
        finally:
            stderr_task.cancel()
            try:
                await stderr_task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.warning("stderr_task raised exception during cleanup: %s", exc)
