# Trading instance image. Runs both the Telegram daemon (long-lived,
# under systemd/docker-compose restart policy) and one-off `run-chain`
# invocations (triggered by host cron via `docker compose run`).
FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1

# Node is required for the Claude Code CLI (`claude -p`), which the
# orchestrator shells out to for every role in the chain (Section 1/4).
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g @anthropic-ai/claude-code \
    && apt-get purge -y curl gnupg \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
COPY mcp_servers/market_data/requirements.txt ./mcp_servers/market_data/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir -r mcp_servers/market_data/requirements.txt

COPY . .

# Runtime auth for `claude -p` (Agent SDK headless credit, Section 5) and
# the Telegram bridge both come from the environment at container start --
# see deploy/.env.example. Nothing secret is baked into this image.
ENTRYPOINT ["python", "-m", "hermes.cli"]
CMD ["telegram-daemon"]
