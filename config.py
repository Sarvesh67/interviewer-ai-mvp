"""
Configuration management for AI Interviewer
Handles API keys and settings for all providers
"""
import os
from typing import Optional
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings with API keys"""
    
    # Hedra API Configuration
    HEDRA_API_KEY: Optional[str] = None
    HEDRA_API_URL: str = "https://api.hedra.com/web-app/public"
    
    # Google Gemini API Configuration
    GEMINI_API_KEY: Optional[str] = None
    GEMINI_MODEL: str = "gemini-2.0-flash-exp"  # Using latest available model
    
    # Anthropic Claude API Configuration
    ANTHROPIC_API_KEY: Optional[str] = None
    CLAUDE_MODEL: str = "claude-3-5-sonnet-20241022"  # Better reasoning for scoring
    
    # LiveKit Configuration
    LIVEKIT_URL: Optional[str] = None
    LIVEKIT_API_KEY: Optional[str] = None
    LIVEKIT_API_SECRET: Optional[str] = None
    
    # OpenAI Configuration (for STT/TTS if needed)
    OPENAI_API_KEY: Optional[str] = None
    
    # Deepgram Configuration (Alternative STT)
    DEEPGRAM_API_KEY: Optional[str] = None
    
    # ElevenLabs Configuration (Alternative TTS)
    ELEVENLABS_API_KEY: Optional[str] = None
    
    # Application Settings
    UPLOAD_DIR: str = "uploads"
    MAX_INTERVIEW_DURATION_MINUTES: int = 45
    DEFAULT_DIFFICULTY_LEVEL: str = "intermediate"  # junior, intermediate, senior
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


# Global settings instance
settings = Settings()


def validate_api_keys() -> dict:
    """
    Validate that all required API keys are configured
    Returns dict with status of each provider
    """
    status = {
        "hedra": {
            "configured": bool(settings.HEDRA_API_KEY),
            "required": True,
            "message": "Hedra API key is required for avatar creation"
        },
        "gemini": {
            "configured": bool(settings.GEMINI_API_KEY),
            "required": True,
            "message": "Gemini API key is required for question generation"
        },
        "claude": {
            "configured": bool(settings.ANTHROPIC_API_KEY),
            "required": True,
            "message": "Claude API key is required for answer scoring"
        },
        "livekit": {
            "configured": bool(settings.LIVEKIT_URL and settings.LIVEKIT_API_KEY and settings.LIVEKIT_API_SECRET),
            "required": True,
            "message": "LiveKit credentials are required for real-time interviews"
        },
        "openai": {
            "configured": bool(settings.OPENAI_API_KEY),
            "required": False,
            "message": "OpenAI API key is optional (for STT/TTS)"
        },
        "deepgram": {
            "configured": bool(settings.DEEPGRAM_API_KEY),
            "required": False,
            "message": "Deepgram API key is optional (alternative STT)"
        },
        "elevenlabs": {
            "configured": bool(settings.ELEVENLABS_API_KEY),
            "required": False,
            "message": "ElevenLabs API key is optional (alternative TTS)"
        }
    }
    
    return status


def get_missing_required_keys() -> list:
    """Get list of missing required API keys"""
    status = validate_api_keys()
    missing = []
    for provider, info in status.items():
        if info["required"] and not info["configured"]:
            missing.append(provider.upper())
    return missing

