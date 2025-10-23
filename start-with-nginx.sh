#!/bin/bash

# Voice Assistant with Nginx Startup Script
echo "🚀 Starting Voice Assistant with Nginx..."

# Check if .env file exists
if [ ! -f ".env" ]; then
    echo "⚠️  .env file not found!"
    echo "📋 Please create .env file with your credentials:"
    echo ""
    echo "cp env.example .env"
    echo "# Then edit .env with your Twilio credentials"
    echo ""
    exit 1
fi

# Create instance directory if it doesn't exist
mkdir -p instance

# Create nginx directory if it doesn't exist
mkdir -p nginx/conf.d

# Check if nginx configuration exists
if [ ! -f "nginx/nginx.conf" ]; then
    echo "❌ Nginx configuration not found!"
    echo "Please ensure nginx/nginx.conf and nginx/conf.d/voice-assistant.conf exist"
    exit 1
fi

echo "✅ Environment check passed"
echo "🐳 Starting Docker Compose with Nginx..."

# Start with docker-compose
docker-compose up -d

echo ""
echo "🎯 Voice Assistant is running!"
echo "📡 Web interface: http://localhost"
echo "📞 Webhook URL: http://your-domain.com/webhook/voice"
echo "💡 Configure this URL in your Twilio phone number settings"
echo ""
echo "📊 Services:"
echo "  - Voice Assistant: http://localhost (via Nginx)"
echo "  - Direct access: http://localhost:5000 (bypass Nginx)"
echo ""
echo "🔧 Management:"
echo "  - View logs: docker-compose logs -f"
echo "  - Stop: docker-compose down"
echo "  - Restart: docker-compose restart"
echo ""
echo "Press Ctrl+C to view logs, or run 'docker-compose logs -f' to follow logs"
