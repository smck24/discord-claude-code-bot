# Discord → Claude Code bot

A single `/code` slash command in one Discord channel, wired to a local
Claude Code install. Everything in this repo enforces the lockdown from
the Developer Portal walkthrough: one channel, no Message Content
Intent, no shell injection, no permission-bypass mode, a sandboxed
non-root container, rate limiting, and an audit log.

## What you still have to do by hand

I can't click through Discord's website for you — that needs your own
login. Everything below is Discord-side config; everything after that
is this repo.

**Developer Portal**
- [ ] Installation tab → Installation Contexts: **Guild Install** only
- [ ] Bot tab → **Public Bot: OFF**
- [ ] Bot tab → Privileged Gateway Intents: **Presence and Server Members OFF**, **Message Content OFF** (this bot never requests it — see `bot.py`)
- [ ] Installation tab → Default Install Settings → scopes: **`bot`** + **`applications.commands`** only
- [ ] Permissions selected: **View Channel, Send Messages, Read Message History** only — no Administrator, no Manage anything
- [ ] Copy the generated install link, open it, add the bot to your server

**Server settings**
- [ ] Server Settings → Roles → the bot's auto-created role → uncheck **View Channel** at this base/server-wide level
- [ ] Your `#claude` (or `#ai-chat`) channel → Permissions → add the bot's role → **Allow**: View Channel, Send Messages, Read Message History
- [ ] Server Settings → Roles → bot's role → "···" → **View Server As Role** → confirm that channel is the only one it can see
- [ ] Enable Developer Mode (User Settings → Advanced) so you can right-click to copy IDs

If any of this is unfamiliar, it's covered in detail earlier in this conversation — this README assumes it's already done.

## Prerequisites

- Docker + Docker Compose (recommended path), **or** Python 3.11+ and Node.js 20+ if you'd rather run it bare
- A Discord bot already created and invited per the checklist above
- An Anthropic API key (console.anthropic.com)
- A project for Claude Code to work on — anything you're comfortable handing to an agent

## Configure

```bash
cp .env.example .env
```

Fill in `.env`:
- `DISCORD_BOT_TOKEN` — Bot tab → Reset Token
- `DISCORD_GUILD_ID` — right-click your server icon → Copy Server ID
- `CLAUDE_CHANNEL_ID` — right-click `#claude` → Copy Channel ID
- `ANTHROPIC_API_KEY` — console.anthropic.com

Leave `CLAUDE_PERMISSION_MODE=auto` unless you've read the section below and specifically want something else.

## Add your project

Put the repo or files you want Claude Code to work on inside `workspace/`.
That folder is the *only* thing mounted into the container — it's the
entire filesystem the agent can see, by construction. Don't put your
home directory, SSH keys, cloud credentials, or anything you're not
comfortable an LLM-driven agent touching in there.

`workspace/.claude/settings.json` already ships with this repo — keep it.

## Run it

```bash
docker compose up --build -d
docker compose logs -f
```

You should see "Logged in as ... Commands synced to guild ..." in the logs.
`/code` will then show up in your server's command list within a few
seconds (it's a guild-scoped command, so it doesn't take the ~1 hour
that global commands sometimes do).

Without Docker:

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
npm install -g @anthropic-ai/claude-code   # or the installer from docs.claude.com
export WORKSPACE_DIR=$(pwd)/workspace
python3 bot.py
```

## Use it

In `#claude`: `/code fix the failing test in tests/test_parser.py`

Plain messages (not the slash command) get a one-line nudge toward
`/code` and are otherwise ignored — the bot never reads ordinary message
text, since it never requested the Message Content intent.

## What's already decided for you, and how to change it

**Permission mode (`CLAUDE_PERMISSION_MODE` in `.env`, default `auto`).**
Discord messages are untrusted input directing an agent that can run
shell commands and edit files. `auto` mode runs a classifier over each
action and screens content the agent reads for injected instructions,
instead of either asking a human who isn't there (the default mode just
hangs in headless use) or skipping every check (`bypassPermissions` /
`--dangerously-skip-permissions`, which Anthropic's own docs describe as
giving no protection against prompt injection). `workspace/.claude/settings.json`
additionally sets `disableBypassPermissionsMode: "disable"`, so switching
`.env` alone won't silently re-enable the bypass — you'd have to edit
that file too. `plan` mode is worth knowing about: it has Claude Code
produce a plan without executing anything, useful if you want a human
to review before a second `/code` actually does the work.

**Sandbox.** `workspace/.claude/settings.json` turns on Claude Code's
built-in sandbox, which restricts what shell commands can read/write and
reach over the network, independent of permission mode. It also denies
reads of `.env`, `.git/`, `~/.ssh/`, and `~/.aws/` as a second layer on
top of "those credentials shouldn't be in the container at all."

**Container.** Non-root user, nothing mounted except `workspace/`. The
container does need normal outbound network access for the bot's Discord
connection and Claude Code's API calls — it's the sandbox above, not the
container's network, that restricts what shell commands specifically can
reach.

**Rate limit / concurrency.** `MAX_INVOCATIONS_PER_HOUR` (default 20) and
a lock that rejects a second `/code` while one is still running, so two
tasks can't collide in the same workspace.

**Audit log.** Every invocation and its outcome is appended to
`workspace/.audit.log` (persists across container rebuilds since it's in
the mounted volume). It logs the task text and a truncated result/error,
not Claude Code's full internal transcript.

## Things this doesn't do

- It doesn't restrict *which Discord users* can run `/code` — anyone who
  can see `#claude` can direct the agent. If that's not everyone with
  server access, restrict who can view/post in that channel, or add a
  role check in `code_command` before it does anything.
- It doesn't review actions before they happen. `auto` mode classifies
  per-action, but there's no human approval step. If you want one, the
  cleanest place to add it is having Claude Code run in `plan` mode first
  and only executing after a reaction or follow-up command confirms it.

## Troubleshooting

**`claude: command not found`** — set `CLAUDE_BIN` in `.env` to the full
path; check with `docker compose exec claude-bot which claude`.

**First `/code` call hangs or times out** — Claude Code may be waiting on
a first-run prompt unrelated to your task. Try
`docker compose exec claude-bot claude -p "say hello" --permission-mode auto`
once by hand and see what it prints; resolve whatever it's waiting on,
then retry from Discord.

**Command doesn't show up in Discord** — guild commands sync on every
`on_ready`; restart the bot (`docker compose restart`) and check the logs
for the "Commands synced" line. Confirm `DISCORD_GUILD_ID` is your
server, not the application's own ID.

**"Missing Access" errors** — almost always means the bot's role lost
`View Channel` in `#claude` specifically, not a code problem. Re-check
the channel override.

## Final check

- [ ] `/code` only appears as usable in `#claude`, confirmed by trying it in another channel (should get the ephemeral "only works in the designated channel" reply)
- [ ] DMing the bot directly does nothing (no slash command available there; plain DMs are silently ignored by `on_message`)
- [ ] `workspace/.audit.log` is gaining a line per invocation
- [ ] `CLAUDE_PERMISSION_MODE` is `auto`, not `bypassPermissions`, unless you deliberately changed it with the tradeoffs in mind
- [ ] Nothing outside `workspace/` is reachable — check by asking it to read a file you know is outside that folder and confirming it can't
