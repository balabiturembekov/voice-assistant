import os
from datetime import timedelta
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


class Config:
    # Twilio Configuration
    TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
    TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
    TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")

    # Company Information
    COMPANY_NAME = os.getenv("COMPANY_NAME", "Your Company")
    WEBSITE_URL = os.getenv("WEBSITE_URL", "https://your-website.com")

    # Voice Configuration
    VOICE_NAME = os.getenv("VOICE_NAME", "alice")

    # Validate X-Twilio-Signature on /webhook/* (needs TWILIO_AUTH_TOKEN)
    TWILIO_VALIDATE_REQUESTS = (
        os.getenv("TWILIO_VALIDATE_REQUESTS", "True").lower() == "true"
    )

    # AfterBuy Configuration (secrets only from environment)
    AFTERBUY_PARTNER_ID = os.getenv("AFTERBUY_PARTNER_ID")
    AFTERBUY_PARTNER_TOKEN = os.getenv("AFTERBUY_PARTNER_TOKEN")
    AFTERBUY_ACCOUNT_TOKEN = os.getenv("AFTERBUY_ACCOUNT_TOKEN")
    AFTERBUY_USER_ID = os.getenv("AFTERBUY_USER_ID")
    AFTERBUY_USER_PASSWORD = os.getenv("AFTERBUY_USER_PASSWORD")

    # Flask Configuration
    FLASK_ENV = os.getenv("FLASK_ENV", "production")
    FLASK_DEBUG = os.getenv("FLASK_DEBUG", "False").lower() == "true"
    SECRET_KEY = os.getenv("SECRET_KEY")

    # Session cookies (admin login)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = (
        os.getenv("SESSION_COOKIE_SECURE", "True").lower() == "true"
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

    # Email Configuration
    # Support both EMAIL_* and MAIL_* environment variables for compatibility
    MAIL_SERVER = os.getenv("EMAIL_HOST") or os.getenv(
        "MAIL_SERVER", "w01da240.kasserver.com"
    )
    MAIL_PORT = int(os.getenv("EMAIL_PORT") or os.getenv("MAIL_PORT", "587"))
    MAIL_USE_TLS = (
        os.getenv("EMAIL_USE_TLS") or os.getenv("MAIL_USE_TLS", "True")
    ).lower() == "true"
    MAIL_USE_SSL = os.getenv("MAIL_USE_SSL", "False").lower() == "true"
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
