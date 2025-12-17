import os
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

    # AfterBuy Configuration
    AFTERBUY_PARTNER_ID = os.getenv("AFTERBUY_PARTNER_ID", "113464")
    AFTERBUY_PARTNER_TOKEN = os.getenv(
        "AFTERBUY_PARTNER_TOKEN", "6722d455-4d02-4da3-97ef-f5dfcf73656d"
    )
    AFTERBUY_ACCOUNT_TOKEN = os.getenv(
        "AFTERBUY_ACCOUNT_TOKEN", "53217733-1987-4cf8-a065-2c2591e4765c"
    )
    AFTERBUY_USER_ID = os.getenv("AFTERBUY_USER_ID", "Balabi")
    AFTERBUY_USER_PASSWORD = os.getenv("AFTERBUY_USER_PASSWORD", "Parol4Balabi2025!")

    # Flask Configuration
    FLASK_ENV = os.getenv("FLASK_ENV", "production")
    FLASK_DEBUG = os.getenv("FLASK_DEBUG", "False").lower() == "true"

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
    MAIL_SERVER = os.getenv("EMAIL_HOST") or os.getenv("MAIL_SERVER", "w01da240.kasserver.com")
    MAIL_PORT = int(os.getenv("EMAIL_PORT") or os.getenv("MAIL_PORT", "587"))
    MAIL_USE_TLS = (os.getenv("EMAIL_USE_TLS") or os.getenv("MAIL_USE_TLS", "True")).lower() == "true"
    MAIL_USE_SSL = os.getenv("MAIL_USE_SSL", "False").lower() == "true"
    MAIL_USERNAME = os.getenv("EMAIL_HOST_USER") or os.getenv("MAIL_USERNAME", "order@jvmoebel.de")
    MAIL_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD") or os.getenv("MAIL_PASSWORD", "")
    MAIL_DEFAULT_SENDER = os.getenv("DEFAULT_FROM_EMAIL") or os.getenv("MAIL_DEFAULT_SENDER", MAIL_USERNAME)
    MAIL_RECIPIENT = os.getenv(
        "MAIL_RECIPIENT", ""
    )  # Email address to receive voice messages
    EMAIL_CHARSET = os.getenv("EMAIL_CHARSET", "utf-8")
    EMAIL_CONTENT_TYPE = os.getenv("EMAIL_CONTENT_TYPE", "text/plain; charset=utf-8")
