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
    
    
    # Flask Configuration
    FLASK_ENV = os.getenv('FLASK_ENV', 'development')
    FLASK_DEBUG = os.getenv('FLASK_DEBUG', 'True').lower() == 'true'
    
    # Database Configuration
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL', 'sqlite:////home/app/voice_assistant.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
