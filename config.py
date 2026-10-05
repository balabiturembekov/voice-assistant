import os
from datetime import timedelta
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


def env_bool(name, default):
    """'true'/'1'/'yes' (any case) -> True"""
    return os.getenv(name, default).strip().lower() in ("true", "1", "yes")


class Config:
    # Twilio Configuration
    TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
    TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
    TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")

    # Company Information
    COMPANY_NAME = os.getenv("COMPANY_NAME", "JV Möbel")
    WEBSITE_URL = os.getenv("WEBSITE_URL", "https://your-website.com")

    # Text-to-speech voices (Twilio <Say>), one per call language.
    # Generative Google Chirp3-HD voices sound the most natural; alternatives:
    # Polly.Vicki-Generative, Polly.Vicki-Neural, Google.de-DE-Neural2-H
    VOICE_DE = os.getenv("VOICE_DE", "Google.de-DE-Chirp3-HD-Aoede")
    VOICE_EN = os.getenv("VOICE_EN", "Google.en-US-Chirp3-HD-Aoede")

    # Validate X-Twilio-Signature on /webhook/* (needs TWILIO_AUTH_TOKEN)
    TWILIO_VALIDATE_REQUESTS = (
        env_bool("TWILIO_VALIDATE_REQUESTS", "True")
    )

    # AfterBuy Configuration (secrets only from environment)
    AFTERBUY_PARTNER_ID = os.getenv("AFTERBUY_PARTNER_ID")
    AFTERBUY_PARTNER_TOKEN = os.getenv("AFTERBUY_PARTNER_TOKEN")
    AFTERBUY_ACCOUNT_TOKEN = os.getenv("AFTERBUY_ACCOUNT_TOKEN")
    AFTERBUY_USER_ID = os.getenv("AFTERBUY_USER_ID")
    AFTERBUY_USER_PASSWORD = os.getenv("AFTERBUY_USER_PASSWORD")

    # Flask Configuration
    FLASK_ENV = os.getenv("FLASK_ENV", "production")
    FLASK_DEBUG = env_bool("FLASK_DEBUG", "False")
    SECRET_KEY = os.getenv("SECRET_KEY")

    # Session cookies (admin login)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = (
        env_bool("SESSION_COOKIE_SECURE", "True")
    )
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SECURE = SESSION_COOKIE_SECURE
    PERMANENT_SESSION_LIFETIME = timedelta(hours=12)

    # Database Configuration
    # Use absolute path for local development
    import pathlib

    db_path = pathlib.Path(__file__).parent / "instance" / "voice_assistant.db"
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL", f"sqlite:///{db_path.absolute()}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Call flow v2
    # Team numbers dialled at the same time (comma separated, E.164)
    AGENT_NUMBERS = [
        n.strip() for n in os.getenv("AGENT_NUMBERS", "+4973929378421").split(",") if n.strip()
    ]
    AGENT_DIAL_TIMEOUT = int(os.getenv("AGENT_DIAL_TIMEOUT", "25"))
    # Business hours for transfers: weekdays 0=Mon..6=Sun, local time in TIMEZONE
    BUSINESS_DAYS = os.getenv("BUSINESS_DAYS", "0-4")
    BUSINESS_HOURS = os.getenv("BUSINESS_HOURS", "08:00-17:00")
    TIMEZONE = os.getenv("TIMEZONE", "Europe/Berlin")
    BUSINESS_HOURS_TEXT_DE = os.getenv(
        "BUSINESS_HOURS_TEXT_DE", "montags bis freitags von 8 bis 17 Uhr"
    )
    BUSINESS_HOURS_TEXT_EN = os.getenv(
        "BUSINESS_HOURS_TEXT_EN", "Monday to Friday from 8 am to 5 pm"
    )
    # Production time used for the delivery estimate, in weeks
    PRODUCTION_WEEKS = os.getenv("PRODUCTION_WEEKS", "8-12")

    # Redis: job queue, Afterbuy cache, login throttling
    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    # Run jobs inline instead of via the worker (tests, quick local runs)
    QUEUE_SYNC = env_bool("QUEUE_SYNC", "False")
    # Send the voice message email without transcription if none arrived by then
    VOICE_EMAIL_FALLBACK_DELAY = int(os.getenv("VOICE_EMAIL_FALLBACK_DELAY", "300"))

    # Afterbuy: Twilio waits ~15s for a webhook answer, keep lookups well below
    AFTERBUY_CONNECT_TIMEOUT = float(os.getenv("AFTERBUY_CONNECT_TIMEOUT", "3"))
    AFTERBUY_READ_TIMEOUT = float(os.getenv("AFTERBUY_READ_TIMEOUT", "5"))
    AFTERBUY_CACHE_TTL = int(os.getenv("AFTERBUY_CACHE_TTL", "300"))

    # GDPR: anonymize calls older than N days (purge-old-data); empty = disabled
    DATA_RETENTION_DAYS = int(os.getenv("DATA_RETENTION_DAYS") or 0) or None

    # Email Configuration
    # Support both EMAIL_* and MAIL_* environment variables for compatibility
    MAIL_SERVER = os.getenv("EMAIL_HOST") or os.getenv(
        "MAIL_SERVER", "w01da240.kasserver.com"
    )
    MAIL_PORT = int(os.getenv("EMAIL_PORT") or os.getenv("MAIL_PORT", "587"))
    MAIL_USE_TLS = env_bool("EMAIL_USE_TLS", os.getenv("MAIL_USE_TLS", "True"))
    MAIL_USE_SSL = env_bool("MAIL_USE_SSL", "False")
    MAIL_USERNAME = os.getenv("EMAIL_HOST_USER") or os.getenv("MAIL_USERNAME", "")
    MAIL_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD") or os.getenv("MAIL_PASSWORD", "")
    MAIL_DEFAULT_SENDER = os.getenv("DEFAULT_FROM_EMAIL") or os.getenv(
        "MAIL_DEFAULT_SENDER", MAIL_USERNAME
    )
    MAIL_RECIPIENT = os.getenv(
        "MAIL_RECIPIENT", ""
    )  # Email address to receive voice messages
    EMAIL_CHARSET = os.getenv("EMAIL_CHARSET", "utf-8")
    EMAIL_CONTENT_TYPE = os.getenv("EMAIL_CONTENT_TYPE", "text/plain; charset=utf-8")
    # HELO hostname for SMTP (to fix "helo/hostname mismatch" errors)
    # IMPORTANT: Should match the actual connecting server hostname/IP, not email domain
    # If not set, defaults to None (Python will use system hostname automatically)
    # Only set this if your server requires a specific HELO hostname
    # WARNING: Using MAIL_SERVER here may cause "helo/hostname mismatch" if IP has no PTR record
    MAIL_HELO_HOSTNAME = os.getenv("MAIL_HELO_HOSTNAME")  # Default to None, let Python use system hostname

    # External Transcription Service Configuration
    # Options: 'google', 'deepgram', 'twilio' (default, limited to English)
    TRANSCRIPTION_SERVICE = os.getenv("TRANSCRIPTION_SERVICE", "twilio")
    # Google Cloud Speech-to-Text (requires GOOGLE_APPLICATION_CREDENTIALS env var)
    # Deepgram API Key (sign up at https://deepgram.com/)
    DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY", "")


# Settings without which the app must not run in production
REQUIRED_SETTINGS = (
    "SECRET_KEY",
    "AFTERBUY_PARTNER_ID",
    "AFTERBUY_PARTNER_TOKEN",
    "AFTERBUY_ACCOUNT_TOKEN",
    "AFTERBUY_USER_ID",
    "AFTERBUY_USER_PASSWORD",
)


def missing_settings(config_obj=Config):
    """Return names of required settings that are empty"""
    missing = [name for name in REQUIRED_SETTINGS if not getattr(config_obj, name)]
    if config_obj.TWILIO_VALIDATE_REQUESTS and not config_obj.TWILIO_AUTH_TOKEN:
        missing.append("TWILIO_AUTH_TOKEN")
    return missing
