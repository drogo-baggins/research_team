import asyncio
import json


async def main():
    cmd = [
        "node",
        r"C:\Users\paled\scoop\apps\nodejs\current\bin\node_modules\@mariozechner\pi-coding-agent\dist\cli.js",
        "--mode", "rpc",
        "--model", "github-copilot/claude-haiku-4.5",
        "--no-session",
    ]
    print("Starting pi via node...")
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    print(f"PID={proc.pid}")

    await asyncio.sleep(0.3)
    if proc.returncode is not None:
        err = await proc.stderr.read()
        print(f"Died immediately rc={proc.returncode}: {err.decode(errors='replace')}")
        return

    req = json.dumps({"id": "t1", "type": "prompt", "message": "say hi"}) + "\n"
    print(f"Sending: {req.strip()}")
    proc.stdin.write(req.encode())
    await proc.stdin.drain()

    print("Reading all output lines (30s timeout each)...")
    try:
        while True:
            line = await asyncio.wait_for(proc.stdout.readline(), timeout=30)
            if not line:
                print("EOF")
                break
            raw = line.decode(errors="replace").strip()
            print(f"  LINE: {raw}")
            try:
                data = json.loads(raw)
                if data.get("type") == "agent_end":
                    print("  -> agent_end, done")
                    break
            except json.JSONDecodeError:
                pass
    except asyncio.TimeoutError:
        print("TIMEOUT: no line for 30s")
        try:
            err = await asyncio.wait_for(proc.stderr.read(8192), timeout=2)
            print(f"STDERR: {err.decode(errors='replace')!r}")
        except asyncio.TimeoutError:
            print("STDERR also empty")

    if proc.returncode is None:
        proc.terminate()
    await proc.wait()
    print(f"Process exited rc={proc.returncode}")


asyncio.run(main())
