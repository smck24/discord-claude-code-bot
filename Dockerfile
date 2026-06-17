FROM python:3.12-slim

# --- Node.js (the Claude Code CLI requires it) -----------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates git gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# --- Claude Code CLI ---------------------------------------------------------
# Installed via npm here because it lands at a predictable /usr/local path
# inside a container. On your own machine, prefer the installer linked from
# https://docs.claude.com/en/docs/claude-code/overview instead.
RUN npm install -g @anthropic-ai/claude-code

# --- Non-root user ------------------------------------------------------------
# Never run an autonomous coding agent as root. Claude Code itself refuses
# to use permission-bypass modes as root for this same reason.
RUN useradd --create-home --shell /bin/bash claudebot

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py claude_runner.py ./

RUN mkdir -p /workspace && chown -R claudebot:claudebot /app /workspace

USER claudebot
ENV WORKSPACE_DIR=/workspace
ENV PYTHONUNBUFFERED=1

CMD ["python3", "bot.py"]
