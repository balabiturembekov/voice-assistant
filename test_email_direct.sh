#!/bin/bash
# Direct test of email sending endpoint
# Tests /webhook/recorded and /webhook/transcription with full data

BASE_URL="https://nonpunishable-phantasmagorically-gertha.ngrok-free.dev"
CALL_SID="CA$(date +%s)123"
CALLER_NUMBER="+491234567890"
RECORDING_URL="https://api.twilio.com/2010-04-01/Accounts/ACxxxxx/Recordings/RExxxxx.wav"
RECORDING_SID="RE$(date +%s)"

echo "======================================================================"
echo "  DIRECT EMAIL TEST - Testing /webhook/recorded with transcription"
echo "======================================================================"
echo "Base URL: $BASE_URL"
echo "Call SID: $CALL_SID"
echo "Caller: $CALLER_NUMBER"
echo "Recording URL: $RECORDING_URL"
echo ""

# First, create a call record by calling /webhook/voice
echo "Creating call record..."
curl -X POST "$BASE_URL/webhook/voice" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "From=$CALLER_NUMBER" \
  -d "CallSid=$CALL_SID" \
  -d "CallStatus=ringing" \
  -s > /dev/null

sleep 1

# Test /webhook/recorded with transcription
echo ""
echo "======================================================================"
echo "  Testing /webhook/recorded (should send email if transcription available)"
echo "======================================================================"
curl -X POST "$BASE_URL/webhook/recorded" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "From=$CALLER_NUMBER" \
  -d "CallSid=$CALL_SID" \
  -d "RecordingUrl=$RECORDING_URL" \
  -d "RecordingSid=$RECORDING_SID" \
  -d "RecordingDuration=20" \
  -d "RecordingStatus=completed" \
  -d "Digits=#" \
  -d "RecordingTranscription=Hallo, ich habe eine Frage zu meiner Bestellung Nummer 12345. Können Sie mir bitte helfen?" \
  -w "\n\nHTTP Status: %{http_code}\n" \
  -v 2>&1 | grep -E "(HTTP|Status|email|Email|MAIL|SMTP)" || echo "Response received"

sleep 2

# Test /webhook/transcription (should send email with full transcription)
echo ""
echo "======================================================================"
echo "  Testing /webhook/transcription (should send email with full transcription)"
echo "======================================================================"
curl -X POST "$BASE_URL/webhook/transcription" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "CallSid=$CALL_SID" \
  -d "RecordingSid=$RECORDING_SID" \
  -d "TranscriptionText=Hallo, ich habe eine Frage zu meiner Bestellung Nummer 12345. Können Sie mir bitte helfen? Die Lieferung ist noch nicht angekommen." \
  -d "TranscriptionStatus=completed" \
  -w "\n\nHTTP Status: %{http_code}\n" \
  -v 2>&1 | grep -E "(HTTP|Status|email|Email|MAIL|SMTP)" || echo "Response received"

echo ""
echo "======================================================================"
echo "  EMAIL TEST COMPLETE"
echo "======================================================================"
echo ""
echo "📧 Check your email inbox (MAIL_RECIPIENT) for the voice message notification."
echo ""
echo "💡 To verify email was sent, check:"
echo "   1. Application logs for 'Email sent successfully' messages"
echo "   2. Your email inbox (MAIL_RECIPIENT)"
echo "   3. SMTP server logs (if accessible)"
echo ""

