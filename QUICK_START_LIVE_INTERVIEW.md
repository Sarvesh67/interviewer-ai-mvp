# Quick Start: Live Real-time Interview

## 🎯 Two Interview Modes

### 1. **Real-time Mode** (What You Want!) ⭐
- **Live conversation** with Hedra avatar
- **Automatic answer capture** via speech-to-text
- **No manual submission needed**
- Candidate speaks → STT converts → LLM responds → TTS speaks back

### 2. **API Mode** (For Testing Only)
- Manual answer submission via API
- Used for testing without audio/video
- Not for production interviews

---

## 🚀 Starting a Live Interview (3 Steps)

### **Step 1: Start the Agent Worker** (Required!)

The agent worker is a **separate process** that handles live conversations. **This must be running!**

```bash
# In Terminal 1
cd /Users/sarveshshinde/Downloads/ai-interviewer-main
source venv/bin/activate  # If using virtual environment
python realtime_interview_agent.py dev
```

You should see:
```
LiveKit configuration loaded from settings
Agent worker started...
Waiting for interviews...
```

**Keep this terminal running!** The agent worker listens for new interviews and joins automatically.

---

### **Step 2: Start the API Server**

```bash
# In Terminal 2
cd /Users/sarveshshinde/Downloads/ai-interviewer-main
source venv/bin/activate  # If using virtual environment
uvicorn main:app --reload
```

You should see:
```
INFO:     Uvicorn running on http://0.0.0.0:8000
```

---

### **Step 3: Create and Start Interview**

```bash
# In Terminal 3 (or use Postman/curl)

# 1. Create the interview
curl -X POST "http://localhost:8000/api/v1/interviews/create" \
  -H "Content-Type: application/json" \
  -d '{
    "job_description": "Senior Python Backend Engineer with FastAPI, PostgreSQL, Redis",
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

```bash
# 2. Start the real-time interview
INTERVIEW_ID="interview_abc123"  # Use the ID from above

curl -X POST "http://localhost:8000/api/v1/interviews/$INTERVIEW_ID/start-realtime"
```

**Response:**
```json
{
  "interview_id": "interview_abc123",
  "status": "realtime_started",
  "candidate_join_url": "wss://your-project.livekit.cloud?token=...",
  "candidate_token": "...",
  "livekit_url": "wss://your-project.livekit.cloud"
}
```

---

### **Step 4: Candidate Joins (Browser)**

**Option A: Use the Frontend (Easiest)**

Open in browser:
```
http://localhost:8000/frontend/realtime_interview.html?interview_id=interview_abc123
```

Or use the `candidate_join_url` directly from the API response.

**Option B: Direct URL**

The frontend will:
1. Connect to LiveKit room
2. Request microphone/camera permissions
3. Show candidate video
4. Wait for interviewer to join

---

## 🎬 What Happens Next (Automatic!)

Once the candidate joins:

1. ✅ **Agent worker detects** new participant in room
2. ✅ **Interview agent joins** automatically (you'll see in Terminal 1)
3. ✅ **Hedra avatar appears** (if configured)
4. ✅ **Interviewer greets** candidate: "Hello John! I'm your technical interviewer..."
5. ✅ **First question asked** automatically
6. ✅ **Candidate speaks** → STT converts to text automatically
7. ✅ **LLM evaluates** answer → TTS speaks response
8. ✅ **Follow-ups asked** if answer is unclear
9. ✅ **Next question** asked automatically
10. ✅ **Process repeats** for all questions
11. ✅ **Interview ends** automatically
12. ✅ **Report generated** automatically

**You don't need to do anything!** Answers are captured automatically via speech-to-text.

---

## 📊 Check Interview Status

```bash
# Get interview state
curl "http://localhost:8000/api/v1/interviews/$INTERVIEW_ID/state"

# Get interview report (after completion)
curl "http://localhost:8000/api/v1/interviews/$INTERVIEW_ID/report"
```

---

## 🔍 What You'll See

### In Terminal 1 (Agent Worker):
```
Interview agent entrypoint called
Starting interview agent for interview: interview_abc123
Hedra avatar avatar_xyz started
Candidate said: I would design a REST API using FastAPI...
Candidate said: For caching, I would use Redis...
...
Interview completed
```

### In Browser:
- **Your video** (candidate) - top left
- **Interviewer video** (Hedra avatar) - top right
- **Status**: "Connected" / "Interview in progress"
- **Connection controls**

---

## ⚠️ Common Issues

### "Agent not joining room"

**Problem:** Agent worker not running or not detecting the room.

**Solution:**
1. Check Terminal 1 - agent worker must be running
2. Verify room name matches `interview_id`
3. Check LiveKit credentials in `.env`
4. Look for errors in agent worker logs

### "No audio/video"

**Problem:** Browser permissions or connection issues.

**Solution:**
1. Allow microphone/camera permissions in browser
2. Check browser console for errors
3. Verify LiveKit connection
4. Test with: `curl http://localhost:8000/api/config/status`

### "Hedra avatar not appearing"

**Problem:** Hedra API key or plugin issues.

**Solution:**
1. Check Hedra API key in `.env`
2. Interview will work without avatar (audio-only)
3. Check agent worker logs for Hedra errors

---

## 🎯 Key Points

### ✅ **Answers are Automatic**
- Candidate speaks → STT converts automatically
- No manual API calls needed
- Real-time conversation flow

### ✅ **Agent Worker is Required**
- Must be running in separate terminal
- Handles all interview logic
- Joins rooms automatically

### ✅ **Two Processes Needed**
1. **Agent Worker**: `python realtime_interview_agent.py dev`
2. **API Server**: `uvicorn main:app --reload`

### ✅ **Frontend is Optional**
- Can use LiveKit Web SDK directly
- Frontend just makes it easier
- Can build custom UI

---

## 📝 Complete Example Script

```bash
#!/bin/bash

# Step 1: Create interview
RESPONSE=$(curl -s -X POST "http://localhost:8000/api/v1/interviews/create" \
  -H "Content-Type: application/json" \
  -d '{
    "job_description": "Senior Python Engineer",
    "job_title": "Backend Engineer",
    "candidate_name": "Test Candidate",
    "candidate_email": "test@example.com"
  }')

INTERVIEW_ID=$(echo $RESPONSE | jq -r '.interview_id')
echo "Created interview: $INTERVIEW_ID"

# Step 2: Start real-time interview
curl -X POST "http://localhost:8000/api/v1/interviews/$INTERVIEW_ID/start-realtime"

# Step 3: Open browser
echo "Opening browser..."
open "http://localhost:8000/frontend/realtime_interview.html?interview_id=$INTERVIEW_ID"
```

---

## 🆘 Need Help?

1. **Check agent worker is running**: Terminal 1 should show "Waiting for interviews..."
2. **Check API server is running**: Terminal 2 should show "Uvicorn running..."
3. **Check API keys**: `curl http://localhost:8000/api/config/status`
4. **Check logs**: Look at both terminals for errors
5. **Read docs**: See `HOW_TO_START_INTERVIEW.md` for detailed guide

---

**Remember:** The `/api/v1/interviews/{interview_id}/answer` endpoint is for **testing only**. In real-time mode, answers are captured automatically!
