import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class Config:
    # Twilio Configuration
    TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID')
    TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')
    TWILIO_PHONE_NUMBER = os.getenv('TWILIO_PHONE_NUMBER')
    
    # Company Information
    COMPANY_NAME = os.getenv('COMPANY_NAME', 'Your Company')
    WEBSITE_URL = os.getenv('WEBSITE_URL', 'https://your-website.com')
    
    # Voice Configuration
    VOICE_NAME = os.getenv('VOICE_NAME', 'alice')
    
    # AfterBuy Configuration
    AFTERBUY_PARTNER_ID = os.getenv('AFTERBUY_PARTNER_ID', '113464')
    AFTERBUY_PARTNER_TOKEN = os.getenv('AFTERBUY_PARTNER_TOKEN', '6722d455-4d02-4da3-97ef-f5dfcf73656d')
    AFTERBUY_ACCOUNT_TOKEN = os.getenv('AFTERBUY_ACCOUNT_TOKEN', '53217733-1987-4cf8-a065-2c2591e4765c')
    AFTERBUY_USER_ID = os.getenv('AFTERBUY_USER_ID', 'Balabi')
    AFTERBUY_USER_PASSWORD = os.getenv('AFTERBUY_USER_PASSWORD', 'Parol4Balabi2025!')
    
    
    # Flask Configuration
    FLASK_ENV = os.getenv('FLASK_ENV', 'production')
    FLASK_DEBUG = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'
    
    # Database Configuration
    # Use absolute path for local development
    import pathlib
    db_path = pathlib.Path(__file__).parent / 'instance' / 'voice_assistant.db'
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL', f'sqlite:///{db_path.absolute()}')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
