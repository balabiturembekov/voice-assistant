#!/bin/bash
# Test email sending with HELO fix
# This script simulates a complete call flow that triggers email sending

BASE_URL="${1:-http://localhost:5000}"
CALL_SID="CA$(date +%s)TEST$(date +%N | cut -b1-3)"
CALLER_NUMBER="+491234567890"
RECORDING_URL="https://api.twilio.com/2010-04-01/Accounts/ACxxxxx/Recordings/RExxxxx.wav"
RECORDING_SID="RE$(date +%s)"
RECORDING_DURATION="15"
TRANSCRIPTION_TEXT="Hallo, ich möchte eine Bestellung aufgeben. Bitte rufen Sie mich zurück."

echo "======================================================================"
echo "  TEST: Email sending with HELO fix"
echo "======================================================================"
echo "Base URL: $BASE_URL"
echo "Call SID: $CALL_SID"
echo "Caller: $CALLER_NUMBER"
echo "Recording URL: $RECORDING_URL"
echo "Transcription: $TRANSCRIPTION_TEXT"
echo ""

# Step 1: Create call
echo "Step 1: Creating call..."
curl -X POST "$BASE_URL/webhook/voice" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "From=$CALLER_NUMBER" \
  -d "CallSid=$CALL_SID" \
  -s > /dev/null
echo "✅ Call created"
sleep 1

# Step 2: Consent
echo "Step 2: Consent..."
curl -X POST "$BASE_URL/webhook/consent" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "From=$CALLER_NUMBER" \
  -d "CallSid=$CALL_SID" \
  -d "Digits=1" \
  -s > /dev/null
echo "✅ Consent given"
sleep 1

# Step 3: Order availability
echo "Step 3: Order availability..."
curl -X POST "$BASE_URL/webhook/order_availability" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "From=$CALLER_NUMBER" \
  -d "CallSid=$CALL_SID" \
  -d "Digits=1" \
  -s > /dev/null
echo "✅ Order availability confirmed"
sleep 1

# Step 4: Order number
echo "Step 4: Order number..."
curl -X POST "$BASE_URL/webhook/order" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "From=$CALLER_NUMBER" \
  -d "CallSid=$CALL_SID" \
  -d "Digits=12345#" \
  -s > /dev/null
echo "✅ Order number entered"
sleep 1

# Step 5: Order confirm
echo "Step 5: Order confirmation..."
curl -X POST "$BASE_URL/webhook/order_confirm" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "From=$CALLER_NUMBER" \
  -d "CallSid=$CALL_SID" \
  -d "Digits=1" \
  -s > /dev/null
echo "✅ Order confirmed"
sleep 1

# Step 6: Voice message choice
echo "Step 6: Voice message choice..."
curl -X POST "$BASE_URL/webhook/voice_message" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "From=$CALLER_NUMBER" \
  -d "CallSid=$CALL_SID" \
  -d "Digits=1" \
  -s > /dev/null
echo "✅ Voice message option selected"
sleep 2

# Step 7: Recorded callback (simulates recording completion)
echo "Step 7: Recording completed..."
curl -X POST "$BASE_URL/webhook/recorded" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "From=$CALLER_NUMBER" \
  -d "CallSid=$CALL_SID" \
  -d "RecordingUrl=$RECORDING_URL" \
  -d "RecordingSid=$RECORDING_SID" \
  -d "RecordingDuration=$RECORDING_DURATION" \
  -d "RecordingStatus=completed" \
  -d "Digits=#" \
  -s > /dev/null
echo "✅ Recording callback sent"
sleep 2

# Step 8: Transcription callback (this triggers email sending)
echo "Step 8: Transcription callback (triggers email)..."
RESPONSE=$(curl -X POST "$BASE_URL/webhook/transcription" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "From=$CALLER_NUMBER" \
  -d "CallSid=$CALL_SID" \
  -d "RecordingSid=$RECORDING_SID" \
  -d "TranscriptionText=$TRANSCRIPTION_TEXT" \
  -d "TranscriptionStatus=completed" \
  -s -w "\nHTTP_CODE:%{http_code}")

HTTP_CODE=$(echo "$RESPONSE" | grep "HTTP_CODE" | cut -d: -f2)
echo "✅ Transcription callback sent (HTTP $HTTP_CODE)"

echo ""
echo "======================================================================"
echo "  TEST COMPLETE"
echo "======================================================================"
echo ""
echo "📋 Check application logs for:"
echo "   - HELO hostname usage"
echo "   - Email sending status"
echo "   - Any SMTP errors"
echo ""
echo "📧 Check email inbox (MAIL_RECIPIENT) for the voice message notification."
echo ""
echo "🔍 Expected log messages:"
echo "   - 'Using system hostname as HELO: ...' OR"
echo "   - 'Not specifying local_hostname - letting Python use system default'"
echo "   - 'Email sent successfully to ...' OR"
echo "   - SMTP error details if sending failed"
echo ""
