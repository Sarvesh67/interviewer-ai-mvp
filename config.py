"""
Configuration management for AI Interviewer
Handles API keys and settings for all providers
"""
import os
from typing import Optional

# Load .env file explicitly
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # dotenv not installed, but pydantic-settings will still read .env
    pass

# Import BaseSettings - supports both pydantic-settings v1 and v2
try:
    from pydantic_settings import BaseSettings, SettingsConfigDict
    HAS_SETTINGS_CONFIG = True
except ImportError:
    try:
        from pydantic_settings import BaseSettings
        HAS_SETTINGS_CONFIG = False
    except ImportError:
        raise ImportError(
            "pydantic-settings is required. Install it with: pip install pydantic-settings"
        )


# Create Settings class with appropriate config
if HAS_SETTINGS_CONFIG:
    # Pydantic-settings v2 syntax
    class Settings(BaseSettings):
        """Application settings with API keys"""
        
        model_config = SettingsConfigDict(
            env_file=".env",
            env_file_encoding="utf-8",
            case_sensitive=True,
            extra="ignore"
        )
        
        # Hedra API Configuration
        HEDRA_API_KEY: Optional[str] = None
        HEDRA_API_URL: str = "https://api.hedra.com/web-app/public"
        
        # Google Gemini API Configuration
        GEMINI_API_KEY: Optional[str] = None
        GEMINI_MODEL: str = "gemini-1.5-flash"  # Using stable model (or gemini-2.0-flash if available)
        
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
else:
    # Pydantic-settings v1 syntax
    class Settings(BaseSettings):
        """Application settings with API keys"""
        
        class Config:
            env_file = ".env"
            env_file_encoding = "utf-8"
            case_sensitive = True
        
        # Hedra API Configuration
        HEDRA_API_KEY: Optional[str] = None
        HEDRA_API_URL: str = "https://api.hedra.com/web-app/public"
        
        # Google Gemini API Configuration
        GEMINI_API_KEY: Optional[str] = None
        GEMINI_MODEL: str = "gemini-1.5-flash"  # Using stable model (or gemini-2.0-flash if available)
        
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
            "message": "Deepgram API key is required for real-time STT in this repo's default agent implementation"
        },
        "elevenlabs": {
            "configured": bool(settings.ELEVENLABS_API_KEY),
            "required": False,
            "message": "ElevenLabs API key is required for real-time TTS in this repo's default agent implementation"
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


def get_missing_realtime_keys() -> list:
    """
    Real-time interview prerequisites.

    NOTE: The current `realtime_interview_agent.py` requires Deepgram (STT) and ElevenLabs (TTS).
    If you later implement fallbacks (e.g., OpenAI Whisper/Silero), update this list accordingly.
    """
    missing = []
    # Baseline: everything needed to create/join rooms and run the agent conversation loop.
    if not settings.LIVEKIT_URL or not settings.LIVEKIT_API_KEY or not settings.LIVEKIT_API_SECRET:
        missing.append("LIVEKIT")
    if not settings.GEMINI_API_KEY:
        missing.append("GEMINI")
    if not settings.DEEPGRAM_API_KEY:
        missing.append("DEEPGRAM")
    if not settings.ELEVENLABS_API_KEY:
        missing.append("ELEVENLABS")
    return missing

