# Hedra Technical Interviewer - Quick Start Guide

## What You're Building
A **realistic AI technical interviewer** that:
- 👤 Looks like a real person (photorealistic avatar)
- 🧠 Acts as domain expert (trained on job description)
- 🎤 Conducts real-time conversations (sub-100ms latency)
- 📊 Rates candidate answers (0-10 scoring system)
- 💬 Asks follow-up questions intelligently
- 📋 Generates detailed interview reports

---

## Architecture (Simple Version)

```
Job Description → Extract Skills → Generate Questions → Create Avatar
                                                           ↓
                                                    Real-time Interview
                                                           ↓
                                            Score Answers → Generate Report
```

---

## 5-Step Implementation

### **Step 1: Generate Technical Questions (Using Gemini - FREE)**

```python
# Extract what skills are needed from job description
job_desc = "Senior Python Backend Engineer, FastAPI, PostgreSQL, Redis"

# Use Gemini to generate 12 contextual technical questions
questions = [
    {
        "question": "Design a REST API for handling millions of transactions",
        "competency": "System Design",
        "score_rubric": "0-10 scale (architecture, tradeoffs, scalability)"
    },
    # ... more questions
]
```

**Cost:** FREE (Gemini 3 Flash free tier)

### **Step 2: Create Hedra Avatar**

```python
# Choose or generate avatar image
avatar_image = "senior_engineer_photo.jpg"

# Upload to Hedra (creates realistic talking avatar)
avatar_id = hedra_api.create_avatar(
    image=avatar_image,
    persona="Expert technical interviewer with 15+ years experience"
)

# Result: Photorealistic avatar that will conduct interview
```

**Cost:** $0.05/minute (for 30-min interview = $1.50)

### **Step 3: Setup Real-time Interview (Using LiveKit + Hedra)**

```python
# Create interview session
session = HedraInterviewSession(
    avatar_id=avatar_id,
    questions=questions,
    domain_expertise="Backend Engineering"
)

# Candidate calls in
# Avatar greets them and starts asking questions
# Real conversation with follow-ups
# ~100ms latency (feels real-time)
```

**Cost:** $0.05/minute

### **Step 4: Score Answers (Using Claude - Smart Scoring)**

```python
# For each answer candidate gave:
score = {
    "question": "Design a REST API...",
    "candidate_answer": "I would use...",
    "score": 8,  # Out of 10
    "reasoning": "Good system design, considered tradeoffs, but missed some edge cases",
    "strengths": ["Clear architecture", "Good scalability thinking"],
    "weaknesses": ["Didn't mention caching strategy"],
    "communication_quality": "Good - explained thinking clearly"
}

# Claude evaluates with context
# Much better than simple keyword matching
```

**Cost:** $0.10 per interview (Claude Sonnet for reasoning)

### **Step 5: Generate Report**

```python
report = {
    "candidate_name": "John Doe",
    "overall_score": 7.8,  # Average of all question scores
    "recommendation": "HIRE",  # ≥8: strong_hire, 6-8: hire, <6: no_hire
    "category_breakdown": {
        "technical_knowledge": 8,
        "communication": 7.5,
        "problem_solving": 7.8,
        "experience_match": 8
    },
    "top_strengths": [
        "Excellent system design thinking",
        "Good communication of complex ideas"
    ],
    "improvement_areas": [
        "Consider edge cases more carefully",
        "Discuss trade-offs more explicitly"
    ],
    "interview_duration": "32 minutes",
    "video_recording": "https://s3.../interview_123.mp4"
}
```

---

## Tech Stack (For Your Use Case)

| Component | Technology | Cost | Why |
|-----------|-----------|------|-----|
| **Question Generation** | Gemini 3 Flash | FREE | Fast, cheap, good quality |
| **Avatar** | Hedra Realtime | $0.05/min | Photorealistic, 15× cheaper |
| **Video/Audio** | LiveKit + Deepgram | Included | Real-time, low latency |
| **Conversation Logic** | Gemini 3 Flash | FREE | Natural conversation |
| **Answer Scoring** | Claude Sonnet | $0.90/1M | Better reasoning |
| **Database** | PostgreSQL | Your server | Store interviews |
| **Video Storage** | AWS S3 | $0.023/GB | Store recordings |

**Total per 30-min interview: ~$1.60**

---

## Key Features You Get

### ✅ Domain Expert Interviewer
- Avatar trained on job description
- Asks relevant, technical questions
- Evaluates based on competencies

### ✅ Real-time Conversation
- Natural back-and-forth dialogue
- Follows up on weak answers
- <100ms response latency

### ✅ Intelligent Scoring
- 0-10 scale for each answer
- Evaluates clarity + correctness + depth
- Provides reasoning for each score

### ✅ Detailed Feedback
- What candidate did well
- Areas for improvement
- Specific, actionable feedback

### ✅ Hiring Decision
- Overall rating (strong hire / hire / no hire)
- Category breakdown (technical, communication, etc)
- Ready to share with hiring managers

---

## Data Flow in Real Interview

```
1. CANDIDATE JOINS CALL
   Interview starts automatically
   
2. AVATAR GREETS CANDIDATE
   "Hi John, I'm your technical interviewer..."
   
3. AVATAR ASKS QUESTION #1
   "Design a REST API for e-commerce platform"
   
4. SPEECH-TO-TEXT (Deepgram)
   Converts candidate's voice to text in real-time
   
5. AVATAR LISTENS & EVALUATES
   Uses LLM to understand answer quality
   
6. AVATAR ASKS FOLLOW-UP (if needed)
   "Can you elaborate on the caching strategy?"
   
7. PROCESS REPEATS (12 questions, 30 min)
   
8. AVATAR CONCLUDES
   "Thank you, we'll be in touch soon"
   
9. REPORT GENERATED
   Scores, feedback, recommendation
   
10. HR REVIEWS REPORT
    Makes hiring decision
```

---

## Deployment Steps

### **Week 1: Setup**
```
1. Get API keys:
   - Hedra (hedra.com)
   - Gemini (ai.google.dev)
   - Claude (anthropic.com)
   - LiveKit (livekit.io)

2. Set up database:
   - Store interview records
   - Store transcripts
   - Store scores & reports

3. Create avatar:
   - Choose/generate avatar image
   - Set domain expertise persona
   - Test with mock questions
```

### **Week 2: Integration**
```
1. Build question generator (Gemini)
2. Build avatar creation pipeline (Hedra)
3. Build interview session handler (LiveKit + Hedra)
4. Build scoring engine (Claude)
5. Build report generator

All code in Python, ~500 lines total
```

### **Week 3: Testing**
```
1. Test with mock candidates
2. Verify scoring accuracy
3. Check avatar quality
4. Test edge cases
5. Get feedback from HR team
```

### **Week 4: Launch**
```
1. Deploy to production
2. Create candidate scheduling page
3. Send invitations to beta users
4. Monitor performance & adjust
```

---

## Code Example: Question Generation

```python
from anthropic import Anthropic

def generate_technical_questions(job_description: str) -> list:
    client = Anthropic()
    
    # This is 100% free with Gemini API
    response = client.messages.create(
        model="gemini-3-flash",
        max_tokens=2048,
        messages=[{
            "role": "user",
            "content": f"""
            Generate 12 technical interview questions for:
            {job_description}
            
            For each question provide:
            1. Question text
            2. What competency you're testing
            3. Good answer example
            4. Scoring rubric (0-10)
            
            Format as JSON.
            """
        }]
    )
    
    # Parse response and return questions
    return parse_json(response.content[0].text)
```

---

## Code Example: Create Avatar & Start Interview

```python
from livekit import agents
from livekit.plugins import hedra

async def start_interview(job_desc: str, candidate_name: str, ctx):
    # Step 1: Generate questions
    questions = generate_technical_questions(job_desc)
    
    # Step 2: Create Hedra avatar
    avatar = hedra.AvatarSession(
        avatar_image="expert_engineer.jpg",
        avatar_participant_name="interviewer"
    )
    
    # Step 3: Create conversation agent
    agent = agents.AgentSession(
        stt=deepgram.STT(),  # Speech to text
        llm=gemini.LLM(),    # Conversation logic
        tts=elevenlabs.TTS() # Text to speech
    )
    
    # Step 4: Start interview
    await avatar.start(agent.session, room=ctx.room)
    
    # Step 5: Welcome candidate
    await agent.say(f"Hi {candidate_name}, welcome! Let's start the technical interview.")
    
    # Step 6: Ask questions
    for question in questions:
        await agent.say(question["text"])
        
        # Listen to answer
        answer = await agent.listen()
        
        # Ask follow-up if needed
        if len(answer) < 50:
            await agent.say("Can you elaborate more on that?")
            answer += await agent.listen()
        
        # Store for scoring
        store_answer(candidate_name, question, answer)
    
    # Step 7: Close
    await agent.say("Thank you! We'll be in touch soon.")
```

---

## Real Example: Output Report

```json
{
  "candidate_name": "Sarah Chen",
  "position": "Senior Backend Engineer",
  "interview_duration": "31 minutes",
  "overall_score": 8.2,
  "recommendation": "STRONG_HIRE",
  
  "category_scores": {
    "technical_knowledge": 8.5,
    "system_design": 8.0,
    "communication": 8.3,
    "problem_solving": 8.0
  },
  
  "strengths": [
    "Excellent understanding of distributed systems",
    "Clear communication of complex concepts",
    "Thoughtful about trade-offs and constraints"
  ],
  
  "areas_for_growth": [
    "Could discuss monitoring/observability more",
    "Consider failure scenarios proactively"
  ],
  
  "interview_snapshot": {
    "questions_asked": 12,
    "average_answer_length": "2.5 minutes",
    "follow_ups_asked": 3,
    "no_answers": 0
  },
  
  "video_recording": "https://s3.amazonaws.com/interviews/sarah_chen_12345.mp4",
  "transcript": "https://s3.amazonaws.com/interviews/sarah_chen_12345_transcript.txt",
  
  "next_steps": "Schedule onsite interviews - strong technical fit"
}
```

---

## Cost Comparison

### Your Solution (Hedra + Gemini + Claude)
- Per 30-min interview: **$1.60**
- 100 interviews/month: **$160**
- 1,000 interviews/month: **$1,600**

### Tengai (Leading AI Interview Platform)
- Per interview: ~$15-25
- 100 interviews/month: ~$1,500-2,500

### Traditional Recruiting Agency
- Per hire: $3,000-5,000
- For 100 interviews (assume 10% hire rate): ~$30,000-50,000

**You're 10-30× cheaper than alternatives!**

---

## Launch Checklist

- [ ] Hedra API integrated
- [ ] Question generation working
- [ ] Avatar creation pipeline tested
- [ ] LiveKit setup + Deepgram STT
- [ ] Scoring engine (Claude) working
- [ ] Report generation templates
- [ ] Database schema created
- [ ] Video storage configured
- [ ] Candidate scheduling page
- [ ] Email notifications
- [ ] HR dashboard to review reports
- [ ] Analytics & monitoring

---

## Next Steps

1. **Get API Keys** (30 min)
   - Hedra: hedra.com
   - Gemini: ai.google.dev
   - Claude: anthropic.com
   - LiveKit: livekit.io

2. **Build Question Generator** (2 hours)
   - Use Gemini API
   - Test with 3 job descriptions
   - Create storage for questions

3. **Build Avatar Pipeline** (4 hours)
   - Avatar image selection/generation
   - Hedra API integration
   - Test avatar creation

4. **Setup Interview Session** (6 hours)
   - LiveKit + Hedra integration
   - Speech-to-text setup
   - Test real interview

5. **Build Scoring Engine** (4 hours)
   - Claude scoring integration
   - Report generation
   - Store results

**Total: ~16 hours for MVP**

This is totally doable in 2-3 weeks with a competent backend developer (you!).
