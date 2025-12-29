# Setup Guide: AI Technical Interviewer with Hedra

This guide will help you set up all the necessary API keys and configurations to get your technical interviewer running.

## Prerequisites

- Python 3.10 or higher
- pip (Python package manager)
- Virtual environment (recommended)

## Step 1: Install Dependencies

```bash
# Create virtual environment (recommended)
python -m venv venv

# Activate virtual environment
# On macOS/Linux:
source venv/bin/activate
# On Windows:
venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

## Step 2: Configure API Keys

### 2.1 Create Environment File

```bash
# Copy the example environment file
cp .env.example .env

# Edit .env with your API keys
nano .env  # or use your preferred editor
```

### 2.2 Get Required API Keys

#### **Hedra API** (Required)
1. Go to [https://hedra.com](https://hedra.com)
2. Sign up for an account
3. Navigate to API settings
4. Generate an API key
5. Copy the key to `HEDRA_API_KEY` in `.env`

**Cost:** $0.05/minute for avatar usage

#### **Google Gemini API** (Required)
1. Go to [https://ai.google.dev](https://ai.google.dev)
2. Sign in with your Google account
3. Click "Get API Key" or go to [Google AI Studio](https://makersuite.google.com/app/apikey)
4. Create a new API key
5. Copy the key to `GEMINI_API_KEY` in `.env`

**Cost:** FREE tier available, then pay-as-you-go

#### **Anthropic Claude API** (Required)
1. Go to [https://console.anthropic.com](https://console.anthropic.com)
2. Sign up for an account
3. Navigate to API Keys section
4. Create a new API key
5. Copy the key to `ANTHROPIC_API_KEY` in `.env`

**Cost:** ~$0.90 per 1M tokens (scoring costs ~$0.10 per interview)

#### **LiveKit** (Required for Real-time Interviews)
1. Go to [https://cloud.livekit.io](https://cloud.livekit.io)
2. Sign up for an account
3. Create a new project
4. Go to Project Settings → API Keys
5. Copy:
   - Project URL → `LIVEKIT_URL`
   - API Key → `LIVEKIT_API_KEY`
   - API Secret → `LIVEKIT_API_SECRET`

**Cost:** Free tier available, then pay-as-you-go

### 2.3 Optional API Keys

These are optional but can enhance functionality:

- **OpenAI API**: For Whisper STT or GPT models
  - Get from: [https://platform.openai.com/api-keys](https://platform.openai.com/api-keys)
  
- **Deepgram API**: Alternative STT provider
  - Get from: [https://console.deepgram.com](https://console.deepgram.com)
  
- **ElevenLabs API**: Alternative TTS provider
  - Get from: [https://elevenlabs.io](https://elevenlabs.io)

## Step 3: Verify Configuration

### 3.1 Check API Key Status

Start the server and check configuration:

```bash
# Start the server
uvicorn main:app --reload

# In another terminal, check status
curl http://localhost:8000/api/config/status
```

Or visit: [http://localhost:8000/api/config/status](http://localhost:8000/api/config/status)

You should see:
```json
{
  "api_keys_status": {
    "hedra": {"configured": true, ...},
    "gemini": {"configured": true, ...},
    "claude": {"configured": true, ...},
    ...
  },
  "missing_required_keys": [],
  "all_configured": true
}
```

### 3.2 Test Domain Extraction

Test if Gemini is working:

```python
from domain_extraction import extract_domain_knowledge

job_desc = """
Senior Backend Engineer
- Python, FastAPI, PostgreSQL
- 5+ years experience
- Design scalable APIs
"""

domain = extract_domain_knowledge(job_desc)
print(domain)
```

## Step 4: Test Interview Creation

### 4.1 Create a Test Interview

```bash
curl -X POST "http://localhost:8000/api/v1/interviews/create" \
  -H "Content-Type: application/json" \
  -d '{
    "job_description": "Senior Python Backend Engineer with FastAPI experience",
    "job_title": "Senior Backend Engineer",
    "candidate_name": "Test Candidate",
    "candidate_email": "test@example.com",
    "difficulty_level": "intermediate"
  }'
```

### 4.2 Expected Response

You should receive:
- `interview_id`: Unique interview identifier
- `avatar_id`: Hedra avatar ID
- `total_questions`: Number of questions generated
- `first_question`: First interview question

## Step 5: Understanding the Workflow

### Interview Flow

1. **Create Interview** (`/api/v1/interviews/create`)
   - Extracts domain knowledge from job description
   - Generates technical questions
   - Creates Hedra avatar

2. **Start Interview** (`/api/v1/interviews/{id}/start`)
   - Activates interview session
   - Returns opening message and first question

3. **Submit Answers** (`/api/v1/interviews/{id}/answer`)
   - Submit candidate answers
   - Get next questions
   - Automatic follow-ups if needed

4. **Complete Interview** (`/api/v1/interviews/{id}/complete`)
   - Scores all answers using Claude
   - Generates comprehensive report
   - Saves report to `uploads/` directory

5. **Get Report** (`/api/v1/interviews/{id}/report`)
   - Retrieve final interview report
   - Includes scores, feedback, recommendations

## Step 6: Troubleshooting

### Common Issues

#### "Missing required API keys"
- Check that all required keys are in `.env`
- Verify keys are correct (no extra spaces)
- Restart server after updating `.env`

#### "Error extracting domain knowledge"
- Verify Gemini API key is valid
- Check internet connection
- Try with a simpler job description

#### "Error creating Hedra avatar"
- Verify Hedra API key is valid
- Check Hedra API documentation for endpoint changes
- Avatar creation may fail in test mode - check logs

#### "Error scoring answers"
- Verify Claude API key is valid
- Check API rate limits
- Ensure answers are being submitted correctly

### Debug Mode

Enable debug logging:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

## Step 7: Production Considerations

### Security
- Never commit `.env` file to git
- Use environment variables in production
- Rotate API keys regularly
- Use secrets management (AWS Secrets Manager, etc.)

### Database
- Current implementation uses in-memory storage
- For production, add database (PostgreSQL recommended)
- Store interviews, reports, and sessions

### Scaling
- Use async/await for I/O operations
- Consider Redis for session management
- Use queue system (Celery) for report generation

### Monitoring
- Add logging (Python logging or Sentry)
- Monitor API usage and costs
- Track interview completion rates
- Alert on API failures

## Step 8: Cost Estimation

### Per 30-minute Interview:
- **Hedra Avatar**: $1.50 (30 min × $0.05/min)
- **Gemini (Questions)**: FREE (free tier)
- **Claude (Scoring)**: ~$0.10
- **LiveKit**: FREE (free tier)
- **Total**: ~$1.60 per interview

### Monthly (100 interviews):
- **Hedra**: $75
- **Claude**: $10
- **Infrastructure**: $50
- **Total**: ~$135/month

## Next Steps

1. ✅ Set up all API keys
2. ✅ Test interview creation
3. ✅ Test answer submission
4. ✅ Review generated reports
5. 🔄 Integrate with frontend
6. 🔄 Add real-time LiveKit + Hedra integration
7. 🔄 Deploy to production

## Support

If you encounter issues:
1. Check API key configuration: `/api/config/status`
2. Review server logs for errors
3. Verify API keys are valid and have credits
4. Check provider status pages for outages

## Additional Resources

- [Hedra Documentation](https://docs.hedra.com)
- [Gemini API Docs](https://ai.google.dev/docs)
- [Claude API Docs](https://docs.anthropic.com)
- [LiveKit Docs](https://docs.livekit.io)
- [FastAPI Documentation](https://fastapi.tiangolo.com)

