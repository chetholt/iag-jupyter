#!/usr/bin/env python3
"""
test_jupyter_ws.py
------------------
Verifies the full IAG → Jupyter WebSocket kernel execution path.

Prerequisites:
    pip install websockets

Usage:
    python3 tests/test_jupyter_ws.py [--base-url http://localhost:9080/jupyter]
"""

import asyncio
import json
import sys
import urllib.request
import uuid
import argparse

try:
    import websockets
except ImportError:
    print("ERROR: 'websockets' package not found. Run: pip install websockets")
    sys.exit(1)


def parse_args():
    p = argparse.ArgumentParser(description="Test Jupyter WebSocket via IAG")
    p.add_argument(
        "--base-url",
        default="http://localhost:9080/jupyter",
        help="Base URL of Jupyter as exposed through IAG (default: http://localhost:9080/jupyter)",
    )
    return p.parse_args()


def get_or_create_kernel(base_url: str) -> str:
    """Return the ID of the first running kernel, or start a new one."""
    kernels = json.loads(urllib.request.urlopen(f"{base_url}/api/kernels").read())
    if kernels:
        kid = kernels[0]["id"]
        print(f"  [reuse]  kernel {kid}")
        return kid
    req = urllib.request.Request(
        f"{base_url}/api/kernels",
        method="POST",
        data=b'{"name":"python3"}',
        headers={"Content-Type": "application/json"},
    )
    kernel = json.loads(urllib.request.urlopen(req).read())
    kid = kernel["id"]
    print(f"  [new]    kernel {kid}")
    return kid


async def execute_and_collect(ws_url: str, code: str) -> tuple[str, str]:
    """Open a WebSocket to a kernel channel, execute code, return (stdout, status)."""
    msg_id = str(uuid.uuid4())
    execute_msg = {
        "header": {
            "msg_id": msg_id,
            "msg_type": "execute_request",
            "username": "test",
            "session": str(uuid.uuid4()),
            "version": "5.3",
        },
        "parent_header": {},
        "metadata": {},
        "buffers": [],
        "channel": "shell",
        "content": {
            "code": code,
            "silent": False,
            "store_history": False,
            "allow_stdin": False,
        },
    }

    stdout_lines = []
    status = "unknown"

    async with websockets.connect(ws_url) as ws:
        await ws.send(json.dumps(execute_msg))
        for _ in range(20):
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=10)
                reply = json.loads(raw)
                mt = reply.get("msg_type", "")
                if mt == "stream" and reply["content"].get("name") == "stdout":
                    stdout_lines.append(reply["content"]["text"].rstrip())
                elif mt == "execute_reply":
                    status = reply["content"]["status"]
                    break
            except asyncio.TimeoutError:
                break

    return "\n".join(stdout_lines), status


def main():
    args = parse_args()
    base_url = args.base_url.rstrip("/")
    ws_base = base_url.replace("http://", "ws://").replace("https://", "wss://")

    print(f"\nIAG → Jupyter WebSocket Test")
    print(f"  Base URL : {base_url}")
    print(f"  WS Base  : {ws_base}\n")

    # ── 1. Jupyter REST API reachable via IAG ──────────────────────────────
    print("1. Checking Jupyter API via IAG...")
    try:
        resp = urllib.request.urlopen(f"{base_url}/api/kernelspecs")
        specs = json.loads(resp.read())
        print(f"   ✓ Available kernels: {list(specs.get('kernelspecs', {}).keys())}")
    except Exception as e:
        print(f"   ✗ FAILED: {e}")
        sys.exit(1)

    # ── 2. Start / reuse kernel ────────────────────────────────────────────
    print("2. Getting kernel...")
    kid = get_or_create_kernel(base_url)

    # ── 3. WebSocket kernel execution ──────────────────────────────────────
    ws_url = f"{ws_base}/api/kernels/{kid}/channels"
    print(f"3. Opening WebSocket: {ws_url}")

    code = (
        "import sys, platform\n"
        "print(f'Python {sys.version.split()[0]} on {platform.system()}')\n"
        "print('WebSocket kernel execution via IAG: OK')"
    )

    stdout, status = asyncio.run(execute_and_collect(ws_url, code))

    if status == "ok":
        print(f"   ✓ execute_reply: {status}")
        print(f"   ✓ STDOUT:\n     " + stdout.replace("\n", "\n     "))
    else:
        print(f"   ✗ execute_reply: {status}")
        sys.exit(1)

    print("\nAll checks passed. IAG → Jupyter WebSocket pipeline is working.\n")


if __name__ == "__main__":
    main()
