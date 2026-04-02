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
        GEMINI_MODEL: str = "gemini-3.1-pro-preview"  # For question generation + domain extraction
        GEMINI_FOLLOW_UP_MODEL: str = "gemini-2.0-flash"  # For real-time conversation (speed over depth)
        GEMINI_SCORING_MODEL: str = "gemini-3.1-pro-preview"  # For answer scoring

        # LiveKit Configuration
        LIVEKIT_URL: Optional[str] = None
        LIVEKIT_API_KEY: Optional[str] = None
        LIVEKIT_API_SECRET: Optional[str] = None

        # Deepgram Configuration (STT/TTS)
        DEEPGRAM_API_KEY: Optional[str] = None

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
        GEMINI_MODEL: str = "gemini-3.1-pro-preview"  # For question generation + domain extraction
        GEMINI_FOLLOW_UP_MODEL: str = "gemini-2.0-flash"  # For real-time conversation (speed over depth)
        GEMINI_SCORING_MODEL: str = "gemini-3.1-pro-preview"  # For answer scoring
        
        # LiveKit Configuration
        LIVEKIT_URL: Optional[str] = None
        LIVEKIT_API_KEY: Optional[str] = None
        LIVEKIT_API_SECRET: Optional[str] = None
        
        # Deepgram Configuration (STT/TTS)
        DEEPGRAM_API_KEY: Optional[str] = None
        
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
            "message": "Gemini API key is required for question generation and answer scoring"
        },
        "livekit": {
            "configured": bool(settings.LIVEKIT_URL and settings.LIVEKIT_API_KEY and settings.LIVEKIT_API_SECRET),
            "required": True,
            "message": "LiveKit credentials are required for real-time interviews"
        },
        "deepgram": {
            "configured": bool(settings.DEEPGRAM_API_KEY),
            "required": True,
            "message": "Deepgram API key is required for STT and TTS in real-time interviews"
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

    NOTE: The current agent uses Deepgram for both STT and TTS.
    If you later implement fallbacks, update this list accordingly.
    """
    missing = []
    # Baseline: everything needed to create/join rooms and run the agent conversation loop.
    if not settings.LIVEKIT_URL or not settings.LIVEKIT_API_KEY or not settings.LIVEKIT_API_SECRET:
        missing.append("LIVEKIT")
    if not settings.GEMINI_API_KEY:
        missing.append("GEMINI")
    if not settings.DEEPGRAM_API_KEY:
        missing.append("DEEPGRAM")
    return missing

