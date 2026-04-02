Stop, clean, rebuild, and restart Docker containers for the AI Interviewer app.

## Steps

1. Set Docker path: `export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"`
2. Stop and remove all containers: `docker compose down --remove-orphans`
3. Remove old images: `docker rmi ai-interviewer-main-api ai-interviewer-main-agent 2>/dev/null`
4. Prune dangling images: `docker image prune -f`
5. Rebuild and start in detached mode: `docker compose up --build -d`
6. Wait a few seconds, then verify both containers are healthy: `docker ps --format "table {{.Names}}\t{{.Status}}"`
7. Report the result to the user

## Notes

- All commands must be run from the project root: `/Users/sarveshshinde/Downloads/ai-interviewer-main`
- Docker binary is at `/Applications/Docker.app/Contents/Resources/bin/docker`
- The `api` container has a healthcheck — `agent` depends on it being healthy before starting
- Use `--timeout 300000` on the build step since it can take a few minutes
