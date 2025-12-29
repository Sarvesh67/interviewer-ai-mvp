# How to Start a Live Interview

## Overview

You have **two modes** for conducting interviews:

1. **API Mode** - Manual answer submission (for testing)
2. **Real-time Mode** - Live conversations with Hedra avatar ⭐ **This is what you want!**

## Real-time Interview Flow

```
1. Create Interview (API)
   ↓
2. Start Real-time Interview (API) → Creates LiveKit room
   ↓
3. Candidate Joins (Browser) → Connects to LiveKit room
   ↓
4. Agent Worker Detects → Joins room with Hedra avatar
   ↓
5. Live Conversation → Questions asked, answers captured automatically
   ↓
6. Interview Completes → Report generated automatically
```

## Step-by-Step Guide

### Prerequisites

1. **Agent Worker Running** (Required!)
   ```bash
   python realtime_interview_agent.py dev
   ```
   This must be running for interviews to work.

2. **API Server Running**
   ```bash
   uvicorn main:app --reload
   ```

3. **API Keys Configured**
   - LiveKit credentials
   - Hedra API key
   - STT provider (Deepgram or OpenAI)
   - TTS provider (ElevenLabs or Silero)

### Step 1: Create Interview

```bash
curl -X POST "http://localhost:8000/api/v1/interviews/create" \
  -H "Content-Type: application/json" \
  -d '{
    "job_description": "Senior Python Backend Engineer with FastAPI, PostgreSQL",
    "job_title": "Backend Engineer",
    "candidate_name": "John Doe",
    "candidate_email": "john@example.com",
    "difficulty_level": "intermediate"
  }'
```

**Response:**
```json
{
  "interview_id": "interview_abc123",
  "avatar_id": "avatar_xyz",
  "total_questions": 12,
  ...
}
```

**Save the `interview_id`!**

### Step 2: Start Real-time Interview

```bash
curl -X POST "http://localhost:8000/api/v1/interviews/{interview_id}/start-realtime"
```

**Response:**
```json
{
  "interview_id": "interview_abc123",
  "status": "realtime_started",
  "candidate_join_url": "wss://...?token=...",
  "candidate_token": "...",
  "livekit_url": "wss://..."
}
```

### Step 3: Candidate Joins

**Option A: Use the Frontend (Easiest)**

Open in browser:
```
http://localhost:8000/frontend/realtime_interview.html?interview_id={interview_id}
```

Or use the `candidate_join_url` directly.

**Option B: Custom Integration**

Use the `candidate_token` and `livekit_url` with LiveKit client SDK.

### Step 4: Interview Conducts Automatically

Once candidate joins:

1. ✅ Agent worker detects new participant
2. ✅ Interview agent joins the room
3. ✅ Hedra avatar appears (if configured)
4. ✅ Interviewer greets candidate
5. ✅ Questions asked one by one
6. ✅ Candidate speaks → STT converts to text
7. ✅ LLM evaluates answer → TTS speaks response
8. ✅ Follow-ups asked if needed
9. ✅ Process repeats for all questions
10. ✅ Interview ends automatically
11. ✅ Report generated

**No manual intervention needed!**

## What You See

### In Browser:
- **Your video** (candidate)
- **Interviewer video** (Hedra avatar)
- **Status updates**
- **Connection controls**

### In Agent Worker Terminal:
```
Interview agent entrypoint called
Starting interview agent for interview: interview_abc123
Hedra avatar avatar_xyz started
Candidate said: I would design a REST API using FastAPI...
...
Interview completed
```

## Key Points

### ✅ Automatic Answer Capture
- Candidate speaks → STT converts to text automatically
- No need to manually submit answers
- Answers are captured in real-time

### ✅ Real-time Conversation
- Natural back-and-forth dialogue
- Follow-up questions based on answer quality
- Sub-100ms latency

### ✅ Hedra Avatar
- Photorealistic interviewer
- Lip-synced speech
- Professional appearance

### ✅ Automatic Scoring
- Answers scored after interview
- Report generated automatically
- Available via API

## Troubleshooting

### "Agent not joining room"

**Check:**
1. Agent worker is running: `python realtime_interview_agent.py dev`
2. LiveKit credentials are correct
3. Room name matches interview_id

**Solution:**
```bash
# Check agent worker logs
# Should see: "Interview agent entrypoint called"
```

### "No video/audio"

**Check:**
1. Browser permissions (microphone/camera)
2. LiveKit connection
3. STT/TTS API keys

**Solution:**
- Allow browser permissions
- Check browser console for errors
- Verify API keys: `curl http://localhost:8000/api/config/status`

### "Hedra avatar not appearing"

**Check:**
1. Hedra API key configured
2. Hedra plugin installed
3. Agent worker logs for errors

**Solution:**
- Avatar may work without Hedra (audio-only)
- Check Hedra API key in `.env`
- See agent worker logs

## Complete Example

```bash
# Terminal 1: Start agent worker
python realtime_interview_agent.py dev

# Terminal 2: Start API server
uvicorn main:app --reload

# Terminal 3: Create and start interview
INTERVIEW_ID=$(curl -s -X POST "http://localhost:8000/api/v1/interviews/create" \
  -H "Content-Type: application/json" \
  -d '{
    "job_description": "Senior Python Engineer",
    "job_title": "Backend Engineer",
    "candidate_name": "Test",
    "candidate_email": "test@example.com"
  }' | jq -r '.interview_id')

curl -X POST "http://localhost:8000/api/v1/interviews/$INTERVIEW_ID/start-realtime"

# Open browser:
# http://localhost:8000/frontend/realtime_interview.html?interview_id=$INTERVIEW_ID
```

## Next Steps

1. ✅ Set up all API keys
2. ✅ Start agent worker
3. ✅ Test with a real interview
4. ✅ Review generated reports
5. ✅ Customize frontend if needed

## Documentation

- [REALTIME_SETUP.md](REALTIME_SETUP.md) - Detailed setup guide
- [QUICK_START_REALTIME.md](QUICK_START_REALTIME.md) - Quick reference
- [SETUP_GUIDE.md](SETUP_GUIDE.md) - General setup

---

**Remember:** The agent worker must be running for real-time interviews to work!

