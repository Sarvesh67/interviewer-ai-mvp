# Local Development Guide (Docker)

Run the full AI Interviewer stack locally using Docker Compose.

## Prerequisites

- **Docker** and **Docker Compose** (v2) installed
- API keys for all required services (see below)
- A Google Cloud project for OAuth (free)

## 1. Environment Setup

```bash
cp env_template.txt .env
```

Open `.env` and fill in every key:

| Variable | Where to get it | Required |
|----------|----------------|----------|
| `HEDRA_API_KEY` | [hedra.com](https://hedra.com) | Yes |
| `GEMINI_API_KEY` | [ai.google.dev](https://ai.google.dev) — used for question gen + answer scoring | Yes |
| `LIVEKIT_URL` | [cloud.livekit.io](https://cloud.livekit.io) — format: `wss://your-project.livekit.cloud` | Yes |
| `LIVEKIT_API_KEY` | LiveKit Cloud dashboard | Yes |
| `LIVEKIT_API_SECRET` | LiveKit Cloud dashboard | Yes |
| `DEEPGRAM_API_KEY` | [console.deepgram.com](https://console.deepgram.com) — STT + TTS | Yes |
| `GOOGLE_CLIENT_ID` | Google Cloud Console (see Section 2) | Yes |
| `ALLOWED_ORIGINS` | Set to `*` for local dev | Optional |

## 2. Google OAuth Setup (for authentication)

All API endpoints require a Google OAuth token. To set this up locally:

1. Go to [Google Cloud Console > Credentials](https://console.cloud.google.com/apis/credentials)
2. Create a project (or select an existing one)
3. Click **Create Credentials > OAuth 2.0 Client ID**
4. Application type: **Web application**
5. Under **Authorized JavaScript origins**, add:
   - `http://localhost:8000`
6. Under **Authorized redirect URIs**, add:
   - `http://localhost:8000`
7. Copy the **Client ID** and paste it as `GOOGLE_CLIENT_ID` in your `.env`

For local testing without the frontend OAuth flow, you can get a test token:
1. Go to [Google OAuth Playground](https://developers.google.com/oauthplayground/)
2. Select "Google OAuth2 API v2" > `openid`, `email`, `profile`
3. Click "Authorize APIs" and sign in
4. Click "Exchange authorization code for tokens"
5. Copy the `id_token` from the response — use this as your Bearer token

## 3. Build and Run

```bash
# Build both containers
docker compose build

# Start the stack (detached)
docker compose up -d
```

This starts two containers:
- **api** — FastAPI server on port 8000 (also serves the frontend)
- **agent** — LiveKit agent worker (connects outbound to LiveKit Cloud, no ports exposed)

Both containers share the `interview_data` volume for session files.

## 4. Verify It's Running

```bash
# Health check
curl http://localhost:8000/
# Expected: {"status":"AI Technical Interviewer API","version":"1.0.0",...}

# Check all API keys are configured
curl http://localhost:8000/api/config/status
# Expected: "all_configured": true

# Check container logs
docker compose logs api      # should show "Uvicorn running on 0.0.0.0:8000"
docker compose logs agent    # should show "LiveKit configuration loaded from settings"
```

Frontend is served at: [http://localhost:8000/realtime_interview.html](http://localhost:8000/realtime_interview.html)

## 5. Run a Test Interview

### Step 1: Create an interview

```bash
curl -X POST http://localhost:8000/api/v1/interviews/create \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_GOOGLE_ID_TOKEN" \
  -d '{
    "job_description": "Senior Python Backend Engineer with FastAPI, PostgreSQL, Redis experience. Must have 5+ years building scalable APIs.",
    "job_title": "Senior Backend Engineer",
    "candidate_name": "Test Candidate",
    "candidate_email": "test@example.com",
    "difficulty_level": "intermediate"
  }'
```

Save the `interview_id` from the response.

### Step 2: Start a real-time interview

```bash
curl -X POST http://localhost:8000/api/v1/interviews/INTERVIEW_ID/start-realtime \
  -H "Authorization: Bearer YOUR_GOOGLE_ID_TOKEN"
```

This creates a LiveKit room and returns a `candidate_join_url`.

### Step 3: Join as candidate

Open [http://localhost:8000/realtime_interview.html?interview_id=INTERVIEW_ID](http://localhost:8000/realtime_interview.html?interview_id=INTERVIEW_ID) in your browser.

Click **Connect to Interview**. Allow microphone and camera access. The AI interviewer (Hedra avatar) will greet you and begin asking questions.

### Step 4: Complete and get report

After the interview ends (or to end it manually):

```bash
# Complete the interview and generate scoring report
curl -X POST http://localhost:8000/api/v1/interviews/INTERVIEW_ID/complete \
  -H "Authorization: Bearer YOUR_GOOGLE_ID_TOKEN"

# Get the full report
curl http://localhost:8000/api/v1/interviews/INTERVIEW_ID/report \
  -H "Authorization: Bearer YOUR_GOOGLE_ID_TOKEN"
```

## 6. Logs and Debugging

```bash
# Follow all logs in real-time
docker compose logs -f

# API server only
docker compose logs -f api

# Agent worker only
docker compose logs -f agent

# Check if agent joined the LiveKit room
curl http://localhost:8000/api/v1/interviews/INTERVIEW_ID/realtime/participants \
  -H "Authorization: Bearer YOUR_GOOGLE_ID_TOKEN"
```

### Common Issues

| Problem | Fix |
|---------|-----|
| `ModuleNotFoundError` in logs | Rebuild: `docker compose build --no-cache` |
| Agent not joining room | Check `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` in `.env`. Run `docker compose logs agent` for details. |
| Avatar not showing | Check `HEDRA_API_KEY`. Avatar creation is best-effort — interview works without it. |
| 401 on API calls | Your Google ID token expired (1 hour TTL). Get a fresh one from OAuth Playground. |
| `"all_configured": false` | One or more API keys missing in `.env`. Check `/api/config/status` for details. |
| Port 8000 in use | Stop other services on 8000, or change port in `docker-compose.yml`: `"8001:8000"` |

## 7. Stop Everything

```bash
docker compose down          # stop containers, keep volumes
docker compose down -v       # stop containers AND delete volumes (clears interview data)
```

## Architecture

```
Browser (localhost:8000)
    |
    v
[Caddy / Direct] --> [api container :8000]
                         |
                         | writes session JSON
                         v
                    [interview_store/ volume]
                         ^
                         | reads session JSON
                         |
                    [agent container]
                         |
                         v
                    LiveKit Cloud (WebRTC)
                         |
                    Deepgram (STT + TTS) + Hedra (Avatar)
```

## Repository

GitHub: [https://github.com/Sarvesh67/interviewer-ai-mvp](https://github.com/Sarvesh67/interviewer-ai-mvp)
