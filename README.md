# 🎯 AI Technical Interviewer with Hedra

A production-ready AI-powered technical interview system that creates domain-expert interviewers using Hedra avatars, generates contextual questions from job descriptions, and provides intelligent answer scoring.

## ✨ Features

- **🎭 Hedra Avatar Integration**: Photorealistic AI interviewer avatars
- **🧠 Domain Expertise**: Extracts technical requirements from job descriptions
- **❓ Intelligent Question Generation**: Creates contextual technical questions using Gemini
- **📊 AI-Powered Scoring**: Evaluates answers with detailed reasoning using Claude
- **💬 Real-time Interviews**: LiveKit integration for real-time conversations
- **📋 Comprehensive Reports**: Detailed feedback with ratings and recommendations

## 🏗️ Architecture

```
Job Description
    ↓
Domain Knowledge Extraction (Gemini)
    ↓
Technical Question Generation (Gemini)
    ↓
Hedra Avatar Created (Domain Expert Persona)
    ↓
Real-time Interview Session (LiveKit + Hedra)
    ↓
Answer Scoring & Rating (Claude)
    ↓
Detailed Interview Report
```

## 🚀 Quick Start

### 1. Install Dependencies

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure API Keys

```bash
# Copy environment template
cp env_template.txt .env

# Edit .env and add your API keys
nano .env  # or use your preferred editor
```

**Required API Keys:**
- **Hedra**: Get from [hedra.com](https://hedra.com)
- **Gemini**: Get from [ai.google.dev](https://ai.google.dev)
- **Claude**: Get from [console.anthropic.com](https://console.anthropic.com)
- **LiveKit**: Get from [cloud.livekit.io](https://cloud.livekit.io)

See [SETUP_GUIDE.md](SETUP_GUIDE.md) for detailed setup instructions.

### 3. Verify Configuration

```bash
# Run quick start check
python quick_start.py
```

### 4. Start Server

```bash
uvicorn main:app --reload
```

### 5. Test API

Visit [http://localhost:8000/docs](http://localhost:8000/docs) for interactive API documentation.

## 📖 Usage

### Create an Interview

```bash
curl -X POST "http://localhost:8000/api/v1/interviews/create" \
  -H "Content-Type: application/json" \
  -d '{
    "job_description": "Senior Python Backend Engineer with FastAPI, PostgreSQL, Redis experience",
    "job_title": "Senior Backend Engineer",
    "candidate_name": "John Doe",
    "candidate_email": "john@example.com",
    "difficulty_level": "intermediate"
  }'
```

### Start Interview

```bash
curl -X POST "http://localhost:8000/api/v1/interviews/{interview_id}/start"
```

### Submit Answers

```bash
curl -X POST "http://localhost:8000/api/v1/interviews/{interview_id}/answer" \
  -H "Content-Type: application/json" \
  -d '{
    "interview_id": "interview_abc123",
    "question_idx": 0,
    "transcript": "I would design a REST API using FastAPI..."
  }'
```

### Complete Interview & Get Report

```bash
curl -X POST "http://localhost:8000/api/v1/interviews/{interview_id}/complete"
curl -X GET "http://localhost:8000/api/v1/interviews/{interview_id}/report"
```

## 📁 Project Structure

```
.
├── main.py                  # FastAPI application with all endpoints
├── config.py                # Configuration and API key management
├── domain_extraction.py     # Extract domain knowledge from job descriptions
├── question_generator.py    # Generate technical questions
├── hedra_avatar.py          # Hedra avatar creation and persona
├── interview_session.py     # Interview session management
├── answer_scoring.py        # Score answers using Claude
├── report_generator.py      # Generate comprehensive reports
├── quick_start.py           # Quick setup verification script
├── requirements.txt         # Python dependencies
├── env_template.txt         # Environment variables template
├── SETUP_GUIDE.md          # Detailed setup instructions
└── uploads/                 # Interview reports storage
```

## 🔧 API Endpoints

### Configuration
- `GET /api/config/status` - Check API key configuration status

### Interview Management
- `POST /api/v1/interviews/create` - Create new interview
- `POST /api/v1/interviews/{id}/start` - Start interview session
- `GET /api/v1/interviews/{id}/state` - Get interview state
- `POST /api/v1/interviews/{id}/answer` - Submit candidate answer
- `POST /api/v1/interviews/{id}/complete` - Complete interview and generate report
- `GET /api/v1/interviews/{id}/report` - Get interview report
- `GET /api/v1/interviews/{id}` - Get interview details

## 💰 Cost Breakdown

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

## 🎯 Key Features

### Domain Expert Interviewer
- Avatar trained on job description
- Asks relevant, technical questions
- Evaluates based on competencies

### Intelligent Question Generation
- Contextual questions based on job requirements
- Mix of design, implementation, and scenario questions
- Difficulty levels: junior, intermediate, senior

### AI-Powered Scoring
- 0-10 scale for each answer
- Evaluates clarity + correctness + depth
- Provides detailed reasoning

### Comprehensive Reports
- Overall score and recommendation
- Category breakdown (technical, communication, depth)
- Top strengths and areas for improvement
- Detailed Q&A with scores

## 🛠️ Tech Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **Backend** | FastAPI | REST API framework |
| **Question Generation** | Google Gemini | Generate contextual questions |
| **Answer Scoring** | Anthropic Claude | Intelligent answer evaluation |
| **Avatar** | Hedra | Photorealistic interviewer |
| **Real-time** | LiveKit | WebRTC for interviews |
| **Storage** | Local filesystem | Interview reports |

## 📚 Documentation

- [SETUP_GUIDE.md](SETUP_GUIDE.md) - Complete setup instructions
- [Hedra-Interviewer-Implementation.md](Hedra-Interviewer-Implementation.md) - Technical implementation details
- [Hedra-Quick-Start.md](Hedra-Quick-Start.md) - Quick start guide

## 🔒 Security Notes

- Never commit `.env` file to git
- Use environment variables in production
- Rotate API keys regularly
- Use secrets management for production

## 🚧 Production Considerations

- Replace in-memory storage with database (PostgreSQL)
- Add authentication and authorization
- Implement rate limiting
- Add monitoring and logging
- Use queue system for report generation
- Add caching for frequently accessed data

## 📝 License

This project is private and proprietary.

## 🤝 Support

For issues or questions:
1. Check [SETUP_GUIDE.md](SETUP_GUIDE.md)
2. Verify API keys: `/api/config/status`
3. Review server logs
4. Check provider status pages

---

**Built with ❤️ for efficient technical hiring**
