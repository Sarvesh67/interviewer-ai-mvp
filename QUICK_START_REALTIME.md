# Quick Start: Real-time Interviews

## Two Ways to Use the System

### 1. **API Mode** (Manual Answer Submission)
- Create interview via API
- Submit answers via API endpoints
- Get report at the end
- **Use case**: Testing, automated flows, or when you want manual control

### 2. **Real-time Mode** (Live Conversations) ⭐
- Create interview via API
- Candidate joins via web browser
- Real-time conversation with Hedra avatar
- Automatic answer capture and scoring
- **Use case**: Actual candidate interviews

## Quick Start: Real-time Interview

### Step 1: Start Agent Worker

```bash
# Terminal 1: Start the agent worker
python realtime_interview_agent.py dev
```

This worker will handle all live interviews.

### Step 2: Start API Server

```bash
# Terminal 2: Start the API
uvicorn main:app --reload
```

### Step 3: Create Interview

```bash
curl -X POST "http://localhost:8000/api/v1/interviews/create" \
  -H "Content-Type: application/json" \
  -d '{
    "job_description": "Senior Python Backend Engineer with FastAPI",
    "job_title": "Backend Engineer",
    "candidate_name": "John Doe",
    "candidate_email": "john@example.com"
  }'
```

Save the `interview_id` from the response.

### Step 4: Start Real-time Interview

```bash
curl -X POST "http://localhost:8000/api/v1/interviews/{interview_id}/start-realtime"
```

This creates a LiveKit room and returns connection details.

### Step 5: Candidate Joins

Open in browser:
```
http://localhost:8000/frontend/realtime_interview.html?interview_id={interview_id}
```

Or use the `candidate_join_url` from Step 4.

### Step 6: Interview Happens Automatically

1. Candidate joins room
2. Agent worker detects and joins
3. Hedra avatar appears
4. Interviewer greets candidate
5. Questions asked one by one
6. Candidate speaks, answers captured
7. Follow-ups asked if needed
8. Interview completes automatically
9. Report generated

## What Happens During Interview

```
Candidate speaks → STT converts to text → LLM evaluates → 
TTS generates response → Hedra avatar speaks → Next question
```

All happens in real-time with <100ms latency.

## Key Differences

| Feature | API Mode | Real-time Mode |
|---------|----------|----------------|
| **Answer Submission** | Manual API calls | Automatic (speech-to-text) |
| **Interviewer** | Text responses | Hedra avatar (video) |
| **Interaction** | Request/Response | Live conversation |
| **Use Case** | Testing, automation | Real interviews |

## Troubleshooting

**Agent not joining?**
- Check agent worker is running: `python realtime_interview_agent.py dev`
- Check LiveKit credentials in `.env`
- Check room name matches interview_id

**No video/audio?**
- Allow browser permissions
- Check LiveKit connection
- Verify STT/TTS API keys

**See [REALTIME_SETUP.md](REALTIME_SETUP.md) for detailed setup**

