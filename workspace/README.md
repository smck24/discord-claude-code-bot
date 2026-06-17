# Workspace

Put the project you want Claude Code to work on **inside this folder**.

This directory is the only thing mounted into the bot's container (see
`docker-compose.yml`) — it's the entire filesystem Claude Code can see or
touch when it runs. Nothing outside this folder is reachable from a
Discord message, by construction, not just by convention.

`.claude/settings.json` in here is Claude Code's project config for this
workspace (permission mode, sandbox, deny rules). Keep it even if you
replace everything else in this folder with your own project.
