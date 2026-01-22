"""
Quick Start Script
Helps verify API key configuration and test the system
"""
import os
import sys
from config import settings, validate_api_keys, get_missing_required_keys


def check_environment():
    """Check if .env file exists"""
    if not os.path.exists(".env"):
        print("❌ .env file not found!")
        print("\n📝 To create .env file:")
        print("   1. Copy env_template.txt to .env")
        print("   2. Fill in your API keys")
        print("   3. Run this script again\n")
        return False
    print("✅ .env file found")
    return True


def check_api_keys():
    """Check API key configuration"""
    print("\n🔑 Checking API Key Configuration...")
    print("=" * 60)
    
    status = validate_api_keys()
    missing = get_missing_required_keys()
    
    for provider, info in status.items():
        icon = "✅" if info["configured"] else "❌"
        required = " (REQUIRED)" if info["required"] else " (optional)"
        print(f"{icon} {provider.upper()}: {info['message']}{required}")
    
    print("=" * 60)
    
    if missing:
        print(f"\n⚠️  Missing required API keys: {', '.join(missing)}")
        print("\n📚 Get your API keys:")
        print("   - Hedra: https://hedra.com")
        print("   - Gemini: https://ai.google.dev")
        print("   - Claude: https://console.anthropic.com")
        print("   - LiveKit: https://cloud.livekit.io")
        return False
    else:
        print("\n✅ All required API keys are configured!")
        return True


def test_domain_extraction():
    """Test domain knowledge extraction"""
    print("\n🧪 Testing Domain Knowledge Extraction...")
    print("=" * 60)
    
    try:
        from domain_extraction import extract_domain_knowledge
        
        test_job_desc = """
        Senior Backend Engineer
        - Python, FastAPI, PostgreSQL
        - 5+ years experience
        - Design scalable REST APIs
        - Microservices architecture
        """
        
        print("Extracting domain knowledge from test job description...")
        domain = extract_domain_knowledge(test_job_desc)
        
        print("✅ Domain extraction successful!")
        print(f"   - Job Title: {domain.get('job_title', 'N/A')}")
        print(f"   - Domain Areas: {', '.join(domain.get('domain_areas', [])[:3])}")
        print(f"   - Technologies: {', '.join(domain.get('technologies', [])[:5])}")
        return True
        
    except Exception as e:
        print(f"❌ Domain extraction failed: {e}")
        return False


def test_question_generation():
    """Test question generation"""
    print("\n🧪 Testing Question Generation...")
    print("=" * 60)
    
    try:
        from domain_extraction import extract_domain_knowledge
        from question_generator import generate_technical_questions
        
        test_job_desc = """
        Senior Backend Engineer
        - Python, FastAPI, PostgreSQL
        """
        
        print("Generating test questions...")
        domain = extract_domain_knowledge(test_job_desc)
        num_questions=3
        questions = generate_technical_questions(domain, difficulty_level="intermediate", num_questions=num_questions)
        
        print(f"✅ Generated {len(questions)} questions!")
        for i, q in enumerate(questions[:num_questions], 1):
            print(f"   {i}. {q.get('question', 'N/A')[:60]}...")
        return True
        
    except Exception as e:
        print(f"❌ Question generation failed: {e}")
        return False


def main():
    """Main quick start function"""
    print("🚀 AI Technical Interviewer - Quick Start Check")
    print("=" * 60)
    
    # Check environment
    if not check_environment():
        sys.exit(1)
    
    # Check API keys
    if not check_api_keys():
        print("\n⚠️  Please configure all required API keys before proceeding.")
        sys.exit(1)
    
    # Test domain extraction
    if not test_domain_extraction():
        print("\n⚠️  Domain extraction test failed.")
        sys.exit(1)
    
    # Test question generation
    if not test_question_generation():
        print("\n⚠️  Question generation test failed.")
        sys.exit(1)
    
    print("\n" + "=" * 60)
    print("✅ All checks passed! System is ready to use.")
    print("=" * 60)
    print("\n📖 Next steps:")
    print("   1. Start the server: uvicorn main:app --reload")
    print("   2. Visit: http://localhost:8000/docs for API documentation")
    print("   3. Create an interview: POST /api/v1/interviews/create")
    print("\n📚 See SETUP_GUIDE.md for detailed instructions")


if __name__ == "__main__":
    main()

