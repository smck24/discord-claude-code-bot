"""
Runs the Claude Code CLI headlessly (`claude -p ...`) as a subprocess.

Two things matter most here:
  1. We use create_subprocess_exec (argv list), never a shell. The task
     string is passed as a single literal argument, so there is no shell
     metacharacter injection risk no matter what someone types in Discord.
  2. We never default to a permission-bypass mode. Discord messages are
     untrusted input to an agent that can run shell commands and edit
     files, so the default here is Claude Code's "auto" mode, which runs
     a classifier over each action instead of skipping the checks
     entirely. See the README for how/why to change this.
"""

import asyncio
import os
import logging

from dotenv import load_dotenv

load_dotenv()  # safe to call even when running under Docker with no .env file present

logger = logging.getLogger("claude_runner")

CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")
WORKSPACE_DIR = os.environ.get("WORKSPACE_DIR", "/workspace")
PERMISSION_MODE = os.environ.get("CLAUDE_PERMISSION_MODE", "auto")
TIMEOUT_SECONDS = int(os.environ.get("CLAUDE_TIMEOUT_SECONDS", "300"))


class ClaudeCodeError(Exception):
    """Raised when the claude subprocess fails, times out, or can't be found."""


async def run_claude_code(task: str) -> str:
    """
    Run Claude Code headlessly on `task`, with its working directory
    locked to WORKSPACE_DIR. Returns the captured stdout. Raises
    ClaudeCodeError on a non-zero exit, timeout, or missing binary.
    """
    cmd = [
        CLAUDE_BIN,
        "-p", task,
        "--permission-mode", PERMISSION_MODE,
    ]
    logger.info("Running Claude Code (mode=%s, timeout=%ss): %.200s",
                PERMISSION_MODE, TIMEOUT_SECONDS, task)

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=WORKSPACE_DIR,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as e:
        raise ClaudeCodeError(
            f"Could not find '{CLAUDE_BIN}' on PATH. Set CLAUDE_BIN in .env to "
            f"the full path (check with `docker compose exec claude-bot which claude`)."
        ) from e

    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise ClaudeCodeError(f"Timed out after {TIMEOUT_SECONDS}s and was killed.")

    if proc.returncode != 0:
        err_text = stderr.decode(errors="replace").strip()
        raise ClaudeCodeError(err_text[-1500:] if err_text else f"Exit code {proc.returncode}")

    return stdout.decode(errors="replace").strip()
