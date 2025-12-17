#!/bin/bash

# Test script for email sending via curl requests
# This simulates Twilio webhook calls

BASE_URL="${1:-http://localhost:5000}"

echo "=========================================="
echo "Testing Email Sending via Webhooks"
echo "=========================================="
echo "Base URL: $BASE_URL"
echo ""

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Test 1: German call with recording
echo -e "${BLUE}========================================${NC}"
echo -e "${YELLOW}Test 1: German call - Recording completed${NC}"
echo -e "${BLUE}========================================${NC}"

CALL_SID_DE="TEST_CALL_DE_$(date +%s)"

# Step 1: Create call record
echo -e "${YELLOW}Step 1: Creating call record...${NC}"
RESPONSE=$(curl -X POST "$BASE_URL/webhook/voice" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "CallSid=$CALL_SID_DE" \
  -d "From=%2B491234567890" \
  -w "\nHTTP_STATUS:%{http_code}" \
  -s)

HTTP_STATUS=$(echo "$RESPONSE" | grep -o "HTTP_STATUS:[0-9]*" | cut -d: -f2)

if [ "$HTTP_STATUS" = "200" ]; then
    echo -e "${GREEN}✓ Call record created${NC}"
else
    echo -e "${RED}✗ Failed to create call record (HTTP $HTTP_STATUS)${NC}"
fi

sleep 1

# Step 2: Send recording
echo -e "${YELLOW}Step 2: Sending recording...${NC}"
RESPONSE=$(curl -X POST "$BASE_URL/webhook/recorded" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "CallSid=$CALL_SID_DE" \
  -d "From=%2B491234567890" \
  -d "RecordingUrl=https://api.twilio.com/2010-04-01/Accounts/ACxxx/Recordings/REtest123" \
  -d "RecordingSid=REtest123" \
  -d "RecordingDuration=25" \
  -d "RecordingStatus=completed" \
  -d "RecordingTranscription=Dies ist eine Testnachricht auf Deutsch. Bitte antworten Sie auf diese E-Mail." \
  -d "Digits=%23" \
  -w "\nHTTP_STATUS:%{http_code}" \
  -s)

HTTP_STATUS=$(echo "$RESPONSE" | grep -o "HTTP_STATUS:[0-9]*" | cut -d: -f2)

if [ "$HTTP_STATUS" = "200" ]; then
    echo -e "${GREEN}✓ Recording webhook sent successfully (HTTP $HTTP_STATUS)${NC}"
    echo -e "${GREEN}  → Email should be sent to configured recipient${NC}"
else
    echo -e "${RED}✗ Recording webhook failed (HTTP $HTTP_STATUS)${NC}"
fi

echo ""
sleep 2

# Test 2: English call with recording
echo -e "${BLUE}========================================${NC}"
echo -e "${YELLOW}Test 2: English call - Recording completed${NC}"
echo -e "${BLUE}========================================${NC}"

CALL_SID_EN="TEST_CALL_EN_$(date +%s)"

# Step 1: Create call record
echo -e "${YELLOW}Step 1: Creating call record...${NC}"
RESPONSE=$(curl -X POST "$BASE_URL/webhook/voice" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "CallSid=$CALL_SID_EN" \
  -d "From=%2B1234567890" \
  -w "\nHTTP_STATUS:%{http_code}" \
  -s)

HTTP_STATUS=$(echo "$RESPONSE" | grep -o "HTTP_STATUS:[0-9]*" | cut -d: -f2)

if [ "$HTTP_STATUS" = "200" ]; then
    echo -e "${GREEN}✓ Call record created${NC}"
else
    echo -e "${RED}✗ Failed to create call record (HTTP $HTTP_STATUS)${NC}"
fi

sleep 1

# Step 2: Send recording
echo -e "${YELLOW}Step 2: Sending recording...${NC}"
RESPONSE=$(curl -X POST "$BASE_URL/webhook/recorded" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "CallSid=$CALL_SID_EN" \
  -d "From=%2B1234567890" \
  -d "RecordingUrl=https://api.twilio.com/2010-04-01/Accounts/ACxxx/Recordings/REtest456" \
  -d "RecordingSid=REtest456" \
  -d "RecordingDuration=30" \
  -d "RecordingStatus=completed" \
  -d "RecordingTranscription=This is a test message in English. Please reply to this email." \
  -d "Digits=%23" \
  -w "\nHTTP_STATUS:%{http_code}" \
  -s)

HTTP_STATUS=$(echo "$RESPONSE" | grep -o "HTTP_STATUS:[0-9]*" | cut -d: -f2)

if [ "$HTTP_STATUS" = "200" ]; then
    echo -e "${GREEN}✓ Recording webhook sent successfully (HTTP $HTTP_STATUS)${NC}"
    echo -e "${GREEN}  → Email should be sent to configured recipient${NC}"
else
    echo -e "${RED}✗ Recording webhook failed (HTTP $HTTP_STATUS)${NC}"
fi

echo ""
sleep 2

# Test 3: Transcription callback (updates email with full transcription)
echo -e "${BLUE}========================================${NC}"
echo -e "${YELLOW}Test 3: Transcription callback (updates email)${NC}"
echo -e "${BLUE}========================================${NC}"

CALL_SID_TRANS="TEST_CALL_TRANS_$(date +%s)"

# Step 1: Create call record
echo -e "${YELLOW}Step 1: Creating call record...${NC}"
RESPONSE=$(curl -X POST "$BASE_URL/webhook/voice" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "CallSid=$CALL_SID_TRANS" \
  -d "From=%2B491234567890" \
  -w "\nHTTP_STATUS:%{http_code}" \
  -s)

HTTP_STATUS=$(echo "$RESPONSE" | grep -o "HTTP_STATUS:[0-9]*" | cut -d: -f2)

if [ "$HTTP_STATUS" = "200" ]; then
    echo -e "${GREEN}✓ Call record created${NC}"
else
    echo -e "${RED}✗ Failed to create call record (HTTP $HTTP_STATUS)${NC}"
fi

sleep 1

# Step 2: Send recording first (to create conversation entry with URL)
echo -e "${YELLOW}Step 2: Sending recording (to create conversation entry)...${NC}"
curl -X POST "$BASE_URL/webhook/recorded" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "CallSid=$CALL_SID_TRANS" \
  -d "From=%2B491234567890" \
  -d "RecordingUrl=https://api.twilio.com/2010-04-01/Accounts/ACxxx/Recordings/REtrans123" \
  -d "RecordingSid=REtrans123" \
  -d "RecordingDuration=20" \
  -d "RecordingStatus=completed" \
  -d "RecordingTranscription=" \
  -d "Digits=%23" \
  -s -o /dev/null

sleep 1

# Step 3: Send transcription callback
echo -e "${YELLOW}Step 3: Sending transcription callback...${NC}"
RESPONSE=$(curl -X POST "$BASE_URL/webhook/transcription" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "CallSid=$CALL_SID_TRANS" \
  -d "RecordingSid=REtrans123" \
  -d "TranscriptionText=Dies ist die vollständige Transkription der Sprachnachricht. Sie wurde erfolgreich verarbeitet und an das Team weitergeleitet." \
  -d "TranscriptionStatus=completed" \
  -w "\nHTTP_STATUS:%{http_code}" \
  -s)

HTTP_STATUS=$(echo "$RESPONSE" | grep -o "HTTP_STATUS:[0-9]*" | cut -d: -f2)

if [ "$HTTP_STATUS" = "200" ]; then
    echo -e "${GREEN}✓ Transcription callback sent successfully (HTTP $HTTP_STATUS)${NC}"
    echo -e "${GREEN}  → Updated email with full transcription should be sent${NC}"
else
    echo -e "${RED}✗ Transcription callback failed (HTTP $HTTP_STATUS)${NC}"
fi

echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "${YELLOW}Tests completed!${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo "Next steps:"
echo "  1. Check your email inbox (configured MAIL_RECIPIENT)"
echo "  2. Check Flask server logs for any errors"
echo "  3. Verify emails contain:"
echo "     - Caller number"
echo "     - Recording URL"
echo "     - Transcription text"
echo "     - Duration"
echo "     - Order number (if available)"
echo ""

