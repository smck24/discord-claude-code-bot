"""
Discord bot that exposes a single /code slash command, wired to Claude Code.

Safety properties this file enforces (on top of the Discord-side lockdown
you configure in the Developer Portal / Server Settings):
  - Only requests Intents.default() — no Message Content, no Presence,
    no Server Members. We never read raw message text; the slash command's
    parsed option is all we use.
  - Re-checks the channel ID on every invocation. Discord's per-server
    permissions don't restrict *which channel* a guild-scoped slash
    command can be run in, so this check is doing real work, not just
    defense in depth.
  - on_message ignores DMs and anything outside the target channel. This
    is the only thing that can stop the bot from acting on a DM, since
    Discord's permission overwrites don't apply to direct messages at all.
  - A simple in-memory rate limit and a run-lock so two tasks can't hit
    the same workspace directory at once.
  - Every invocation (and outcome) is appended to an audit log file.
"""

import os
import asyncio
import logging
from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv()

import discord
from discord import app_commands

from claude_runner import run_claude_code, ClaudeCodeError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("claude_bot")


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"Missing required environment variable: {name} (check your .env file)")
    return value


DISCORD_TOKEN = _require_env("DISCORD_BOT_TOKEN")
GUILD_ID = int(_require_env("DISCORD_GUILD_ID"))
CLAUDE_CHANNEL_ID = int(_require_env("CLAUDE_CHANNEL_ID"))

MAX_PER_HOUR = int(os.environ.get("MAX_INVOCATIONS_PER_HOUR", "20"))
AUDIT_LOG_PATH = os.environ.get("AUDIT_LOG_PATH", "/workspace/.audit.log")

_invocation_times: list[float] = []
_run_lock = asyncio.Lock()

intents = discord.Intents.default()
intents.message_content = False  # explicit: we never request this

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)


def _rate_limited() -> bool:
    now = datetime.now(timezone.utc).timestamp()
    cutoff = now - 3600
    while _invocation_times and _invocation_times[0] < cutoff:
        _invocation_times.pop(0)
    return len(_invocation_times) >= MAX_PER_HOUR


def _audit(user: str, task: str, status: str, detail: str = "") -> None:
    line = f"{datetime.now(timezone.utc).isoformat()}\t{user}\t{status}\t{task!r}"
    if detail:
        line += f"\t{detail!r}"
    try:
        with open(AUDIT_LOG_PATH, "a") as f:
            f.write(line + "\n")
    except OSError:
        logger.exception("Could not write audit log at %s", AUDIT_LOG_PATH)


def _chunks(text: str, size: int = 1900) -> list[str]:
    text = text or "(no output)"
    return [text[i:i + size] for i in range(0, len(text), size)]


@tree.command(name="code", description="Send a task to Claude Code", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(task="What should Claude Code do?")
async def code_command(interaction: discord.Interaction, task: str):
    # The real enforcement point: a guild-scoped command can still be run
    # from any channel in that guild, so this check is what actually
    # confines it to one channel.
    if interaction.channel_id != CLAUDE_CHANNEL_ID:
        await interaction.response.send_message(
            "This command only works in the designated channel.", ephemeral=True
        )
        return

    if _rate_limited():
        await interaction.response.send_message(
            f"Hit the rate limit ({MAX_PER_HOUR}/hour). Try again later.", ephemeral=True
        )
        return

    if _run_lock.locked():
        await interaction.response.send_message(
            "Another task is already running in this workspace — please wait for it to finish.",
            ephemeral=True,
        )
        return

    await interaction.response.defer(thinking=True)
    _invocation_times.append(datetime.now(timezone.utc).timestamp())
    logger.info("Invocation by %s: %.200s", interaction.user, task)

    async with _run_lock:
        try:
            result = await run_claude_code(task)
            _audit(str(interaction.user), task, "ok", result[:500])
        except ClaudeCodeError as e:
            _audit(str(interaction.user), task, "error", str(e)[:500])
            await interaction.followup.send(f"Claude Code failed:\n```\n{str(e)[:1500]}\n```")
            return
        except Exception as e:  # noqa: BLE001 - last-resort guard so the bot never crashes
            logger.exception("Unexpected error running Claude Code")
            _audit(str(interaction.user), task, "unexpected_error", str(e)[:500])
            await interaction.followup.send("Something unexpected went wrong. Check the bot logs.")
            return

    pieces = _chunks(result)
    await interaction.followup.send(f"```\n{pieces[0]}\n```")
    for piece in pieces[1:6]:  # cap how many follow-up messages a single run can send
        await interaction.channel.send(f"```\n{piece}\n```")


@client.event
async def on_message(message: discord.Message):
    # We deliberately never read message.content (no Message Content
    # Intent requested). This only checks *where* a message came from.
    if message.author.bot or message.guild is None:
        return  # ignore other bots and, importantly, all DMs
    if message.channel.id != CLAUDE_CHANNEL_ID:
        return  # ignore every channel except the configured one
    try:
        await message.channel.send("Use `/code <task>` to give me something to do.", delete_after=10)
    except discord.Forbidden:
        pass


@client.event
async def on_ready():
    await tree.sync(guild=discord.Object(id=GUILD_ID))
    logger.info("Logged in as %s. Commands synced to guild %s.", client.user, GUILD_ID)


def main():
    client.run(DISCORD_TOKEN)


if __name__ == "__main__":
    main()
