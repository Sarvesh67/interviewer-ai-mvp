# Real-time Interview Setup Guide

This guide explains how to set up and run **live interviews** where candidates can have real-time conversations with the Hedra avatar interviewer.

## Overview

The real-time interview system uses:
- **LiveKit** for WebRTC connections (audio/video streaming)
- **Hedra** for photorealistic avatar
- **LiveKit Agents** for running the interview logic
- **STT/TTS** for speech-to-text and text-to-speech

## Architecture

```
Candidate Browser
    ↓ (WebRTC)
LiveKit Room
    ↓
Interview Agent (Python Worker)
    ↓
Hedra Avatar + LLM + STT/TTS
```

## Setup Steps

### 1. Install Dependencies

Make sure you have all required packages:

```bash
pip install -r requirements.txt
```

Key packages for real-time:
- `livekit` - LiveKit SDK
- `livekit-agents` - Agent framework
- `livekit-plugins-*` - STT/TTS plugins

### 2. Configure LiveKit

In your `.env` file:

```env
LIVEKIT_URL=wss://your-project.livekit.cloud
LIVEKIT_API_KEY=your_api_key
LIVEKIT_API_SECRET=your_api_secret
```

### 3. Configure STT/TTS

Choose one or more:

**Option A: Deepgram (Recommended)**
```env
DEEPGRAM_API_KEY=your_deepgram_key
```

**Option B: OpenAI Whisper**
```env
OPENAI_API_KEY=your_openai_key
```

**Option C: ElevenLabs TTS**
```env
ELEVENLABS_API_KEY=your_elevenlabs_key
```

### 4. Start the Agent Worker

The agent worker is a separate process that handles interviews:

```bash
# Development mode (auto-reload)
python realtime_interview_agent.py dev

# Production mode
python realtime_interview_agent.py start
```

The agent worker will:
- Listen for new interview jobs
- Join LiveKit rooms
- Conduct interviews using Hedra avatar
- Handle real-time conversation

### 5. Start the API Server

In a separate terminal:

```bash
uvicorn main:app --reload
```

## How to Start a Live Interview

### Step 1: Create Interview

```bash
curl -X POST "http://localhost:8000/api/v1/interviews/create" \
  -H "Content-Type: application/json" \
  -d '{
    "job_description": "Senior Python Backend Engineer",
    "job_title": "Backend Engineer",
    "candidate_name": "John Doe",
    "candidate_email": "john@example.com"
  }'
```

Response includes `interview_id`.

### Step 2: Start Real-time Interview

```bash
curl -X POST "http://localhost:8000/api/v1/interviews/{interview_id}/start-realtime"
```

Response includes:
- `candidate_join_url` - URL for candidate to join
- `candidate_token` - Access token
- `livekit_url` - LiveKit server URL

### Step 3: Candidate Joins

**Option A: Use the Frontend**

Open `frontend/realtime_interview.html` in a browser with the interview ID:

```
http://localhost:8000/frontend/realtime_interview.html?interview_id={interview_id}
```

**Option B: Use LiveKit Web SDK**

```javascript
import { Room, RoomEvent } from 'livekit-client';

const room = new Room();
await room.connect(livekit_url, candidate_token);

// Handle remote tracks (interviewer video/audio)
room.on(RoomEvent.TrackSubscribed, (track, publication, participant) => {
  if (track.kind === 'video') {
    track.attach(videoElement);
  }
});
```

### Step 4: Interview Conducts Automatically

Once candidate joins:
1. Agent worker detects new participant
2. Interview agent joins the room
3. Hedra avatar appears
4. Interviewer greets candidate
5. Questions are asked one by one
6. Candidate speaks, STT converts to text
7. LLM generates responses
8. TTS speaks through Hedra avatar
9. Interview continues until all questions answered
10. Interview ends, report is generated

## Frontend Integration

The `frontend/realtime_interview.html` file provides a complete example:

1. **Connect Button**: Starts the interview connection
2. **Video Display**: Shows candidate and interviewer video
3. **Status Updates**: Shows connection status
4. **Disconnect Button**: Ends the interview

To use it:

1. Serve the frontend (or open directly)
2. Pass `interview_id` as URL parameter
3. Click "Connect to Interview"
4. Allow microphone/camera permissions
5. Interview starts automatically

## Testing Without Frontend

You can test the agent worker directly:

```python
# In Python
from realtime_interview_manager import RealtimeInterviewManager
from interview_session import TechnicalInterviewSession

# Create interview session (from your existing code)
session = TechnicalInterviewSession(...)

# Create room
manager = RealtimeInterviewManager()
room_info = await manager.create_interview_room(
    interview_id="test_interview",
    interview_session=session,
    candidate_name="Test Candidate"
)

print(f"Candidate join URL: {room_info['candidate_join_url']}")
```

## Troubleshooting

### Agent Not Joining

1. **Check agent worker is running**:
   ```bash
   python realtime_interview_agent.py dev
   ```

2. **Check LiveKit credentials**:
   ```bash
   curl http://localhost:8000/api/config/status
   ```

3. **Check room name matches interview_id**:
   The room name must match the interview_id for the agent to find it.

### No Audio/Video

1. **Check browser permissions**: Allow microphone and camera
2. **Check LiveKit connection**: Verify token is valid
3. **Check agent worker logs**: Look for errors

### Hedra Avatar Not Appearing

1. **Check Hedra API key**: Verify it's configured
2. **Check Hedra plugin**: May need to install separately
3. **Check logs**: Look for Hedra-related errors

### STT/TTS Not Working

1. **Check API keys**: Deepgram, OpenAI, or ElevenLabs
2. **Check network**: Ensure API calls can reach providers
3. **Check logs**: Look for STT/TTS errors

## Production Deployment

### Agent Worker

Deploy the agent worker as a service:

```bash
# Using systemd
[Unit]
Description=LiveKit Interview Agent
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/path/to/project
ExecStart=/path/to/venv/bin/python realtime_interview_agent.py start
Restart=always

[Install]
WantedBy=multi-user.target
```

### Scaling

- Run multiple agent workers for load balancing
- Use LiveKit's distributed agent system
- Store interview sessions in database (not in-memory)

### Monitoring

- Monitor agent worker logs
- Track LiveKit room connections
- Monitor API usage (STT/TTS costs)
- Track interview completion rates

## Cost Considerations

### Per 30-minute Interview:
- **Hedra Avatar**: $1.50 (30 min × $0.05/min)
- **STT (Deepgram)**: ~$0.05
- **TTS (ElevenLabs)**: ~$0.10
- **LLM (Gemini/OpenAI)**: ~$0.05
- **LiveKit**: FREE (free tier)
- **Total**: ~$1.70 per interview

## Next Steps

1. ✅ Set up LiveKit account
2. ✅ Configure API keys
3. ✅ Start agent worker
4. ✅ Test with frontend
5. ✅ Deploy to production

For more details, see:
- [LiveKit Agents Documentation](https://docs.livekit.io/agents/)
- [Hedra Documentation](https://docs.hedra.com)
- [SETUP_GUIDE.md](SETUP_GUIDE.md)

