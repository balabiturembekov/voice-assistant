from flask import Flask, request, Response, render_template
from twilio.twiml.voice_response import VoiceResponse
import logging
import re
from datetime import datetime, timedelta, timezone
from config import Config
from models import db, Call, Conversation, Order, CallStatus
from sqlalchemy import desc
from afterbuy_client import AfterbuyClient
from services import (
    detect_language,
    get_greeting_message,
    format_order_number_for_speech,
    get_goodbye_message,
    get_order_availability_prompt,
    get_order_input_prompt,
    get_no_order_transfer_message,
    check_delivery_overdue,
    get_overdue_delivery_message,
    get_delivery_status_message,
    send_voice_message_email,
)


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config.from_object(Config)

# Initialize database
db.init_app(app)


def create_or_get_call(call_sid, phone_number, language):
    """Create or get existing call record"""
    if not call_sid:
        logger.error("create_or_get_call called with empty call_sid")
        raise ValueError("call_sid cannot be empty")

    call = Call.query.filter_by(call_sid=call_sid).first()
    if not call:
        call = Call(
            call_sid=call_sid,
            phone_number=phone_number or "",
            language=language or "de",
            status=CallStatus.PROCESSING,
        )
        try:
        db.session.add(call)
        db.session.commit()
        logger.info(f"Created new call record: {call_sid}")
        except Exception as e:
            logger.error(f"Error creating call record: {str(e)}")
            db.session.rollback()
            # Try to get existing call again in case of race condition
            call = Call.query.filter_by(call_sid=call_sid).first()
            if not call:
                raise
    return call


def log_conversation(call_id, step, user_input=None, bot_response=None):
    """Log conversation step"""
    if not call_id:
        logger.error(f"log_conversation called with empty call_id for step: {step}")
        return

    conversation = Conversation(
        call_id=call_id, step=step, user_input=user_input, bot_response=bot_response
    )
    try:
    db.session.add(conversation)
    db.session.commit()
    logger.info(f"Logged conversation: {step}")
    except Exception as e:
        logger.error(f"Error logging conversation: {str(e)}, step: {step}")
        db.session.rollback()
        # Continue execution even if logging fails


def update_call_status(call_id, status):
    """Update call status"""
    if not call_id:
        logger.error("update_call_status called with empty call_id")
        return

    call = db.session.get(Call, call_id)
    if call:
        try:
        call.status = status
        db.session.commit()
        logger.info(f"Updated call {call_id} status to {status.value}")
        except Exception as e:
            logger.error(f"Error updating call status: {str(e)}, call_id: {call_id}")
            db.session.rollback()
            # Continue execution even if update fails


def validate_order_number(order_text, language="de"):
    """Validate if the input looks like a real order number"""
    if not order_text or len(order_text.strip()) < 2:
        return False, "too_short"
    
    order_text = order_text.strip().lower()
    
    # Common non-order words that might be misrecognized
    non_order_words = [
        # Entertainment
        "dry",
        "season",
        "episode",
        "movie",
        "film",
        "series",
        "show",
        "lexington",
        "drive",
        "street",
        "avenue",
        "road",
        "boulevard",
        "trocken",
        "saison",
        "episode",
        "film",
        "serie",
        "show",
        "straße",
        "weg",
        "allee",
        "platz",
        "gasse",
        # Greetings and responses
        "hello",
        "hi",
        "yes",
        "no",
        "okay",
        "ok",
        "sure",
        "maybe",
        "hallo",
        "ja",
        "nein",
        "okay",
        "ok",
        "sicher",
        "vielleicht",
        # Service words
        "help",
        "support",
        "service",
        "information",
        "question",
        "hilfe",
        "support",
        "service",
        "information",
        "frage",
        # Common words that are not order numbers
        "the",
        "and",
        "or",
        "but",
        "with",
        "from",
        "to",
        "for",
        "der",
        "die",
        "das",
        "und",
        "oder",
        "aber",
        "mit",
        "von",
        "zu",
        "für",
        # Address components
        "street",
        "avenue",
        "road",
        "boulevard",
        "lane",
        "court",
        "straße",
        "weg",
        "allee",
        "platz",
        "gasse",
        "hof",
    ]
    
    # Check if it contains non-order words (but allow partial matches in longer strings)
    for word in non_order_words:
        if word in order_text:
            # If the text is mostly the non-order word, reject it
            if len(word) >= len(order_text) * 0.5:  # Word is at least 50% of the text
                return False, "contains_non_order_words"
            # If it's a longer string with numbers/patterns, it might be valid
            elif not any(char.isdigit() for char in order_text) and not any(
                pattern in order_text for pattern in ["-", "_", "."]
            ):
                return False, "contains_non_order_words"
    
    # Check if it's mostly letters without numbers (suspicious)
    if order_text.isalpha() and len(order_text) > 10:
        return False, "too_many_letters"
    
    # Check if it contains at least some numbers or common order patterns
    has_numbers = any(char.isdigit() for char in order_text)
    has_common_patterns = any(pattern in order_text for pattern in ["-", "_", ".", " "])
    
    if not has_numbers and not has_common_patterns:
        return False, "no_numbers_or_patterns"
    
    # If it passes all checks, it might be a valid order number
    return True, "valid"


def get_consent_prompts(language):
    """Get consent prompts for different languages"""
    prompts = {
        "de": {
            "yes": "Drücken Sie die 1 für Ja oder die 2 für Nein.",
            "yes_option": "1",
            "no_option": "2",
        },
        "en": {
            "yes": "Press 1 for Yes or 2 for No.",
            "yes_option": "1",
            "no_option": "2",
        },
    }

    return prompts.get(language, prompts["de"])  # Default to German


def get_order_from_afterbuy(order_number):
    """
    Get order data from AfterBuy API by Rechnungsnummer (InvoiceNumber) or OrderID

    Args:
        order_number: The invoice number (Rechnungsnummer) or order ID to look up

    Returns:
        Dictionary with order data or None if not found
    """
    try:
        # Create AfterBuy client using config
        afterbuy_client = AfterbuyClient(
            partner_id=Config.AFTERBUY_PARTNER_ID,
            partner_token=Config.AFTERBUY_PARTNER_TOKEN,
            account_token=Config.AFTERBUY_ACCOUNT_TOKEN,
            user_id=Config.AFTERBUY_USER_ID,
            user_password=Config.AFTERBUY_USER_PASSWORD,
        )

        # First try to find by InvoiceNumber (Rechnungsnummer)
        order_data = afterbuy_client.get_order_by_invoice_number(order_number)

        if order_data:
            logger.info(
                f"Successfully retrieved order by Rechnungsnummer {order_number} from AfterBuy"
            )
            return order_data

        # If not found, try by OrderID
        order_data = afterbuy_client.get_order_by_id(order_number)

        if order_data:
            logger.info(
                f"Successfully retrieved order by OrderID {order_number} from AfterBuy"
            )
            return order_data
        else:
            logger.warning(
                f"Order {order_number} not found in AfterBuy (tried both Rechnungsnummer and OrderID)"
            )
            return None

    except Exception as e:
        logger.error(f"Error retrieving order {order_number} from AfterBuy: {str(e)}")
        return None


def calculate_production_delivery_dates(order_date_str, country_code="DE"):
    """
    Calculate production and delivery dates based on order date and country

    Args:
        order_date_str: Order date from AfterBuy (e.g., '18.10.2025 16:27:55')
        country_code: Country code from AfterBuy (default 'DE')

    Returns:
        Dictionary with dates and delivery info
    """
    from datetime import datetime, timedelta

    try:
        # Parse order date - handle both with and without time
        date_part = (
            order_date_str.split()[0] if " " in order_date_str else order_date_str
        )
        order_date = datetime.strptime(date_part, "%d.%m.%Y")

        # Production weeks based on country (from bot_messages.txt)
        production_weeks = {
            "TR": (6, 10),  # Turkey: 6-10 weeks
            "CN": (8, 12),  # China: 8-12 weeks
            "PL": (4, 8),  # Poland: 4-8 weeks
            "IT": (4, 8),  # Italy: 4-8 weeks
            "DE": (8, 12),  # Germany (default): 8-12 weeks
        }

        weeks = production_weeks.get(country_code, (8, 12))

        # Calculate production time
        production_start = order_date + timedelta(
            days=7
        )  # Production starts 1 week after order

        # Calculate actual dates based on weeks
        production_min_weeks = weeks[0]
        production_max_weeks = weeks[1]

        production_min = production_start + timedelta(weeks=weeks[0])
        production_max = production_start + timedelta(weeks=weeks[1])

        # Delivery time (production_max + 1-2 weeks for shipping)
        delivery_date = production_max + timedelta(weeks=2)

        # Calculate calendar week
        def get_calendar_week(date):
            """Calculate ISO calendar week"""
            return date.isocalendar()[1]

        delivery_week = get_calendar_week(delivery_date)
        year = delivery_date.year

        return {
            "order_date": order_date.strftime("%d.%m.%Y"),
            "order_date_formatted": order_date.strftime("%d.%m.%Y"),
            "production_start_date": production_start.strftime("%d.%m.%Y"),
            "production_min_weeks": production_min_weeks,
            "production_max_weeks": production_max_weeks,
            "delivery_week": delivery_week,
            "delivery_year": year,
            "delivery_date_start": (delivery_date - timedelta(days=3)).strftime(
                "%d.%m.%Y"
            ),
            "delivery_date_end": (delivery_date + timedelta(days=3)).strftime(
                "%d.%m.%Y"
            ),
            "promised_delivery_date": delivery_date.strftime(
                "%Y-%m-%d"
            ),  # For database storage
        }
    except Exception as e:
        logger.error(f"Error calculating dates: {e}")
        # Return fallback dates with all required fields including promised_delivery_date
        from datetime import datetime, timedelta

        fallback_date = datetime(2025, 10, 22)
        return {
            "order_date": order_date_str,
            "order_date_formatted": "22.10.2025",
            "production_start_date": "22.10.2025",
            "production_min_weeks": 6,
            "production_max_weeks": 10,
            "delivery_week": 42,
            "delivery_year": 2025,
            "delivery_date_start": "13.10.2025",
            "delivery_date_end": "19.10.2025",
            "promised_delivery_date": fallback_date.strftime(
                "%Y-%m-%d"
            ),  # Required field
        }


def format_order_status_for_speech(order_data, language="de", dates_info=None):
    """
    Format order status information for speech output

    Args:
        order_data: Dictionary with order data from AfterBuy
        language: Language code ('de' or 'en')

    Returns:
        Formatted string for speech
    """
    if not order_data:
        if language == "de":
            return "Entschuldigung, ich konnte keine Informationen zu diesem Auftrag finden."
        else:
            return "Sorry, I couldn't find any information about this order."

    # Parse memo for additional info
    memo_data = {}
    if "memo" in order_data and order_data["memo"]:
        from afterbuy_client import AfterbuyClient

        temp_client = AfterbuyClient("", "", "", "", "")
        memo_data = temp_client.parse_memo(order_data["memo"])

    # Get payment info
    payment_info = order_data.get("payment", {})
    already_paid = payment_info.get("already_paid", "0,00")
    full_amount = payment_info.get("full_amount", "0,00")

    # Get buyer info
    buyer_info = order_data.get("buyer", {})
    customer_name = buyer_info.get("first_name", "")
    country = buyer_info.get("country", "DE")

    # Get order date
    order_date = order_data.get("order_date", "18.10.2025 16:27:55")

    # Get payment date (when order was processed)
    payment_date = order_data.get("payment", {}).get("payment_date", order_date)

    # Use provided dates_info or calculate if not provided
    if dates_info is None:
        dates_info = calculate_production_delivery_dates(order_date, country)
        # Add promised delivery date to order_data for overdue checking
        if dates_info and "promised_delivery_date" in dates_info:
            order_data["promised_delivery_date"] = dates_info["promised_delivery_date"]

    # Format amounts (remove commas for speech)
    # AfterBuy uses commas as thousand separators, so we need to handle this properly
    already_paid_clean = already_paid.replace(",", "")
    full_amount_clean = full_amount.replace(",", "")

    # Convert to proper format for speech (e.g., 1680 instead of 168000)
    try:
        # Parse the original amounts correctly
        already_paid_parsed = float(already_paid.replace(",", "."))
        full_amount_parsed = float(full_amount.replace(",", "."))

        # Format for speech (remove decimal if it's .00)
        already_paid_clean = (
            str(int(already_paid_parsed))
            if already_paid_parsed == int(already_paid_parsed)
            else str(already_paid_parsed)
        )
        full_amount_clean = (
            str(int(full_amount_parsed))
            if full_amount_parsed == int(full_amount_parsed)
            else str(full_amount_parsed)
        )
    except (ValueError, TypeError) as e:
        logger.warning(
            f"Error parsing payment amounts: {e}, already_paid={already_paid}, full_amount={full_amount}"
        )
        pass

    if language == "de":
        # Format order ID for speech
        order_id = order_data.get("order_id", "unbekannt")
        order_id_formatted = format_order_number_for_speech(order_id)

        # Safely get dates_info values with fallbacks
        if not dates_info:
            logger.error(
                "dates_info is None or empty in format_order_status_for_speech"
            )
            dates_info = {}
        order_date_formatted = dates_info.get(
            "order_date_formatted", dates_info.get("order_date", "N/A")
        )
        production_start_date = dates_info.get("production_start_date", "N/A")
        production_min_weeks = dates_info.get("production_min_weeks", 6)
        production_max_weeks = dates_info.get("production_max_weeks", 10)
        delivery_week = dates_info.get("delivery_week", 42)
        delivery_year = dates_info.get("delivery_year", 2025)
        delivery_date_start = dates_info.get("delivery_date_start", "N/A")
        delivery_date_end = dates_info.get("delivery_date_end", "N/A")

        status_text = f"""Ihr Auftrag {order_id_formatted}:
Sie haben für Ihren Auftrag insgesamt {already_paid_clean} Euro.
Der gesamte Rechnungsbetrag beträgt {full_amount_clean} Euro.

Der Auftrag wurde durch den Kunden {customer_name} erteilt.
Ihr Auftrag wurde am {order_date_formatted} angenommen und am {production_start_date} an die Produktion übergeben.

Ihre Ware befindet sich derzeit in der Produktion und hat eine voraussichtliche Lieferzeit von {production_min_weeks} bis {production_max_weeks} Wochen.

Wir erwarten die Lieferung in der Kalenderwoche {delivery_week}/{delivery_year}, also in der Woche vom {delivery_date_start} bis {delivery_date_end}.

Wir freuen uns, Ihnen ein hochwertiges Produkt liefern zu dürfen,
und halten Sie selbstverständlich über den weiteren Verlauf auf dem Laufenden."""

    else:
        status_text = (
            f"The status of your order {order_data.get('order_id', 'unknown')} is: "
        )

        if memo_data.get("amount_value", 0) > 0:
            status_text += f"{already_paid_clean} Euros have been paid out of {full_amount_clean} Euros total. "
            if memo_data.get("payment_percent"):
                status_text += f"This represents a {memo_data['payment_percent']} percent down payment. "

        if customer_name:
            status_text += f"The order was placed by {customer_name}. "

        status_text += "You will receive an email with further details."

    return status_text


@app.route("/webhook/voice", methods=["POST"])
def handle_incoming_call():
    """Handle incoming voice calls"""
    try:
        # Get caller information
        caller_number = request.form.get("From", "")
        call_sid = request.form.get("CallSid", "")
        logger.info(f"Incoming call from: {caller_number}")
        
        # Detect language
        language = detect_language(caller_number)
        logger.info(f"Detected language: {language}")
        
        # Create or get call record
        call = create_or_get_call(call_sid, caller_number, language)
        
        # Create TwiML response
        response = VoiceResponse()
        
        # Use static greeting text
        if language == "de":
            # greeting = "Hallo, Sie sprechen mit Liza, Ihrem Sprachassistenten. Dürfen wir Ihr Gespräch zur Qualitätsverbesserung verarbeiten?"
            greeting = get_greeting_message(language)
        else:
            greeting = get_greeting_message(language)
        
        # Speak the greeting
        logger.info(f"Using voice: {Config.VOICE_NAME}")
        response.say(greeting, language=language, voice=Config.VOICE_NAME)
        
        # Log greeting conversation
        log_conversation(call.id, "greeting", bot_response=greeting)
        
        # Get consent prompts
        consent_prompts = get_consent_prompts(language)
        
        # Gather user response for consent
        gather = response.gather(
            input="dtmf",
            timeout=15,
            num_digits=1,
            action="/webhook/consent",
            method="POST",
        )
        
        # If no input, repeat the prompt
        gather.say(
            consent_prompts["yes"],
            language=language,
            voice=Config.VOICE_NAME,
            voice_engine=(
                "neural" if Config.VOICE_NAME.startswith("polly.") else "standard"
            ),
        )
        
        # If no response, say goodbye
        response.say(
            get_goodbye_message(language), language=language, voice=Config.VOICE_NAME
        )
        response.hangup()
        
        return Response(str(response), mimetype="text/xml")
        
    except Exception as e:
        logger.error(f"Error handling incoming call: {str(e)}")
        response = VoiceResponse()
        response.say(
            "Sorry, there was an error. Please try again later.",
            voice=Config.VOICE_NAME,
        )
        response.hangup()
        return Response(str(response), mimetype="text/xml")


@app.route("/webhook/consent", methods=["POST"])
def handle_consent():
    """Handle user consent response"""
    try:
        # Get the DTMF result (keypad input)
        dtmf_result = request.form.get("Digits", "").strip()
        caller_number = request.form.get("From", "")
        call_sid = request.form.get("CallSid", "")
        
        logger.info(f"Consent response from {caller_number}: {dtmf_result}")
        
        # Get call record
        call = Call.query.filter_by(call_sid=call_sid).first()
        if not call:
            logger.error(f"Call record not found for {call_sid}")
            response = VoiceResponse()
            response.say(
                "Sorry, there was an error. Please try again later.",
                voice=Config.VOICE_NAME,
            )
            response.hangup()
            return Response(str(response), mimetype="text/xml")
        
        # Detect language again
        language = detect_language(caller_number)
        consent_prompts = get_consent_prompts(language)
        
        # Log consent conversation
        log_conversation(call.id, "consent", user_input=dtmf_result)
        
        response = VoiceResponse()
        
        # Check for positive consent (1 = Yes, 2 = No)
        if dtmf_result == "1":
            # User consented
            logger.info(f"User {caller_number} consented to data processing")
            
            # Use static consent response
            if language == "de":
                consent_response = "Vielen Dank für Ihre Zustimmung. Bitte teilen Sie mir nun mit, wie ich Ihnen behilflich sein kann."
            else:
                consent_response = "Thank you for your consent. I'm Liza and I'm happy to help you. How can I help you today?"
            response.say(
                consent_response,
                voice=Config.VOICE_NAME,
                voice_engine=(
                    "neural" if Config.VOICE_NAME.startswith("polly.") else "standard"
                ),
            )
            
            # Log consent response and update status
            log_conversation(call.id, "consent_response", bot_response=consent_response)
            update_call_status(call.id, CallStatus.HANDLED)
            
            # Ask if user has order number first
            order_availability_prompt = get_order_availability_prompt(language)
            response.say(
                order_availability_prompt,
                voice=Config.VOICE_NAME,
                voice_engine=(
                    "neural" if Config.VOICE_NAME.startswith("polly.") else "standard"
                ),
            )

            # Log availability question
            log_conversation(
                call.id,
                "order_availability_question",
                bot_response=order_availability_prompt,
            )

            # Gather response about order availability
            gather = response.gather(
                input="dtmf",
                timeout=15,
                num_digits=1,
                action="/webhook/order_availability",
                method="POST",
            )
            
            # If no response, say goodbye
            response.say(get_goodbye_message(language), voice=Config.VOICE_NAME)
            response.hangup()
            
        elif dtmf_result == "2":
            # User declined, but continue anyway
            logger.info(
                f"User {caller_number} declined data processing, but continuing"
            )
            
            # Use static consent response
            if language == "de":
                consent_response = "Danke für Ihren Anruf. Ich helfe Ihnen gerne weiter. Wie kann ich Ihnen behilflich sein?"
            else:
                consent_response = "Thank you for calling. I'm happy to help you. How can I help you today?"
            response.say(
                consent_response,
                voice=Config.VOICE_NAME,
                voice_engine=(
                    "neural" if Config.VOICE_NAME.startswith("polly.") else "standard"
                ),
            )
            
            # Log consent response and update status
            log_conversation(
                call.id, "consent_declined_but_continued", bot_response=consent_response
            )
            update_call_status(call.id, CallStatus.HANDLED)

            # Ask if user has order number first (same as if they consented)
            order_availability_prompt = get_order_availability_prompt(language)
            response.say(
                order_availability_prompt,
                voice=Config.VOICE_NAME,
                voice_engine=(
                    "neural" if Config.VOICE_NAME.startswith("polly.") else "standard"
                ),
            )

            # Log availability question
            log_conversation(
                call.id,
                "order_availability_question",
                bot_response=order_availability_prompt,
            )

            # Gather response about order availability
            gather = response.gather(
                input="dtmf",
                timeout=15,
                num_digits=1,
                action="/webhook/order_availability",
                method="POST",
            )

            # If no response, say goodbye
            response.say(get_goodbye_message(language), voice=Config.VOICE_NAME)
            response.hangup()
            
        else:
            # Invalid response
            logger.warning(
                f"Invalid consent response '{dtmf_result}' from {caller_number}"
            )
            
            # Use static consent response
            if language == "de":
                invalid_response = "Entschuldigung, ich habe Ihre Antwort nicht verstanden. Drücken Sie die 1 für Ja oder die 2 für Nein."
            else:
                invalid_response = "Sorry, I didn't understand your response. Press 1 for Yes or 2 for No."
            
            response.say(
                invalid_response,
                voice=Config.VOICE_NAME,
                voice_engine=(
                    "neural" if Config.VOICE_NAME.startswith("polly.") else "standard"
                ),
            )
            
            # Log invalid response
            log_conversation(call.id, "invalid_consent", bot_response=invalid_response)
            
            # Ask for consent again
            gather = response.gather(
                input="dtmf",
                timeout=15,
                num_digits=1,
                action="/webhook/consent",
                method="POST",
            )
            
            # If no response, say goodbye
            if language == "de":
                response.say(get_goodbye_message(language), voice=Config.VOICE_NAME)
            else:
                response.say(get_goodbye_message(language), voice=Config.VOICE_NAME)
            response.hangup()
        
        return Response(str(response), mimetype="text/xml")
        
    except Exception as e:
        logger.error(f"Error handling consent: {str(e)}")
        response = VoiceResponse()
        response.say(
            "Sorry, there was an error. Please try again later.",
            voice=Config.VOICE_NAME,
        )
        response.hangup()
        return Response(str(response), mimetype="text/xml")


@app.route("/webhook/order_availability", methods=["POST"])
def handle_order_availability():
    """Handle user response about order number availability"""
    try:
        # Get the DTMF result (keypad input)
        dtmf_result = request.form.get("Digits", "").strip()
        caller_number = request.form.get("From", "")
        call_sid = request.form.get("CallSid", "")

        logger.info(f"Order availability response from {caller_number}: {dtmf_result}")

        # Get call record
        call = Call.query.filter_by(call_sid=call_sid).first()
        if not call:
            logger.error(f"Call record not found for {call_sid}")
            response = VoiceResponse()
            response.say(
                "Sorry, there was an error. Please try again later.",
                voice=Config.VOICE_NAME,
            )
            response.hangup()
            return Response(str(response), mimetype="text/xml")

        # Detect language
        language = detect_language(caller_number)

        # Log availability response
        log_conversation(call.id, "order_availability_response", user_input=dtmf_result)

        response = VoiceResponse()

        if dtmf_result == "1":  # User has order number
            logger.info(f"User {caller_number} has order number")

            # Ask for order number with clear instructions
            order_input_prompt = get_order_input_prompt(language)
            response.say(
                order_input_prompt,
                voice=Config.VOICE_NAME,
                voice_engine=(
                    "neural" if Config.VOICE_NAME.startswith("polly.") else "standard"
                ),
            )

            # Log order input request
            log_conversation(
                call.id, "order_input_request", bot_response=order_input_prompt
            )

            # Gather order number via DTMF (keypad)
            gather = response.gather(
                input="dtmf",
                timeout=30,
                finishOnKey="#",
                action="/webhook/order",
                method="POST",
            )

            # If no response, say goodbye
            response.say(get_goodbye_message(language), voice=Config.VOICE_NAME)
            response.hangup()

        elif dtmf_result == "2":  # User doesn't have order number
            logger.info(
                f"User {caller_number} doesn't have order number, transferring to manager"
            )

            # Transfer to manager with explanation
            transfer_msg = get_no_order_transfer_message(language)
            response.say(
                transfer_msg,
                voice=Config.VOICE_NAME,
                voice_engine=(
                    "neural" if Config.VOICE_NAME.startswith("polly.") else "standard"
                ),
            )

            # Log transfer
            log_conversation(
                call.id, "no_order_transfer_to_manager", bot_response=transfer_msg
            )
            update_call_status(call.id, CallStatus.HANDLED)

            # Redirect to manager's phone number
            manager_phone = "+4973929378421"  # 07392 - 93 78 421
            response.dial(number=manager_phone, caller_id=caller_number)

        else:
            # Invalid response or timeout
            logger.warning(
                f"Invalid order availability response '{dtmf_result}' from {caller_number}"
            )

            if language == "de":
                invalid_response = "Entschuldigung, ich habe Ihre Antwort nicht verstanden. Haben Sie eine Rechnungsnummer? Drücken Sie die 1 für Ja oder die 2 für Nein."
            else:
                invalid_response = "Sorry, I didn't understand your response. Do you have an order number? Press 1 for Yes or 2 for No."

            response.say(
                invalid_response,
                voice=Config.VOICE_NAME,
                voice_engine=(
                    "neural" if Config.VOICE_NAME.startswith("polly.") else "standard"
                ),
            )

            # Log invalid response
            log_conversation(
                call.id,
                "invalid_order_availability_response",
                bot_response=invalid_response,
            )

            # Ask again
            gather = response.gather(
                input="dtmf",
                timeout=15,
                num_digits=1,
                action="/webhook/order_availability",
                method="POST",
            )

            # If no response, say goodbye
            response.say(get_goodbye_message(language), voice=Config.VOICE_NAME)
            response.hangup()

        return Response(str(response), mimetype="text/xml")

    except Exception as e:
        logger.error(f"Error handling order availability: {str(e)}")
        response = VoiceResponse()
        response.say(
            "Sorry, there was an error. Please try again later.",
            voice=Config.VOICE_NAME,
        )
        response.hangup()
        return Response(str(response), mimetype="text/xml")


@app.route("/webhook/order", methods=["POST"])
def handle_order():
    """Handle order number input"""
    try:
        # Get the DTMF result (keypad input)
        dtmf_result = request.form.get("Digits", "").strip()
        caller_number = request.form.get("From", "")
        call_sid = request.form.get("CallSid", "")
        
        logger.info(f"Order number from {caller_number}: {dtmf_result}")
        
        # Get call record
        call = Call.query.filter_by(call_sid=call_sid).first()
        if not call:
            logger.error(f"Call record not found for {call_sid}")
            response = VoiceResponse()
            response.say(
                "Sorry, there was an error. Please try again later.",
                voice=Config.VOICE_NAME,
            )
            response.hangup()
            return Response(str(response), mimetype="text/xml")
        
        # Detect language again
        language = detect_language(caller_number)
        
        # Log order input
        log_conversation(call.id, "order_input", user_input=dtmf_result)
        
        response = VoiceResponse()
        
        if dtmf_result:
            # Validate order number
            is_valid, validation_reason = validate_order_number(dtmf_result, language)
            
            if not is_valid:
                # Invalid order number - ask for clarification
                logger.warning(
                    f"Invalid order number '{dtmf_result}' from {caller_number}: {validation_reason}"
                )
                
                if language == "de":
                    invalid_response = f"Entschuldigung, ich habe '{dtmf_result}' nicht als gültige Rechnungsnummer erkannt. Bitte geben Sie Ihre Rechnungsnummer erneut über die Tastatur ein."
                else:
                    invalid_response = f"Sorry, I didn't recognize '{dtmf_result}' as a valid order number. Please enter your order number again using the keypad."
                
                response.say(
                    invalid_response,
                    voice=Config.VOICE_NAME,
                    voice_engine=(
                        "neural"
                        if Config.VOICE_NAME.startswith("polly.")
                        else "standard"
                    ),
                )
                
                # Log invalid response
                log_conversation(
                    call.id, "invalid_order_response", bot_response=invalid_response
                )
                
                # Ask for order number again
                if language == "de":
                    retry_prompt = "Bitte geben Sie Ihre Rechnungsnummer erneut über die Tastatur ein. Drücken Sie die Raute-Taste # wenn Sie fertig sind."
                else:
                    retry_prompt = "Please enter your order number again using the keypad. Press the hash key # when you are finished."
                
                gather = response.gather(
                    input="dtmf",
                    timeout=30,
                    finishOnKey="#",
                    action="/webhook/order",
                    method="POST",
                )
                
                # If no response, say goodbye
                if language == "de":
                    response.say(get_goodbye_message(language), voice=Config.VOICE_NAME)
                else:
                    response.say(get_goodbye_message(language), voice=Config.VOICE_NAME)
                response.hangup()
                
                return Response(str(response), mimetype="text/xml")
            
            # Valid order number - ask for confirmation
            formatted_number = format_order_number_for_speech(dtmf_result)
            if language == "de":
                confirmation_response = f"Sie haben die folgende Rechnungsnummer {formatted_number} eingetippt? Bitte bestätigen Sie durch 1 für Ja oder 2 für Nein."
            else:
                confirmation_response = f"You have entered order number {formatted_number}. Is this correct? Press 1 for Yes or 2 for No."
            
            response.say(
                confirmation_response,
                voice=Config.VOICE_NAME,
                voice_engine=(
                    "neural" if Config.VOICE_NAME.startswith("polly.") else "standard"
                ),
            )
            
            # Log confirmation request
            log_conversation(
                call.id,
                "order_confirmation_request",
                bot_response=confirmation_response,
            )
            
            # Gather confirmation (1 for Yes, 2 for No)
            gather = response.gather(
                input="dtmf",
                timeout=10,
                num_digits=1,
                action="/webhook/order_confirm",
                method="POST",
            )
            
            # If no response, say goodbye
            if language == "de":
                response.say(get_goodbye_message(language), voice=Config.VOICE_NAME)
            else:
                response.say(get_goodbye_message(language), voice=Config.VOICE_NAME)
            response.hangup()
            
            return Response(str(response), mimetype="text/xml")

        else:
            # No order number provided - timeout or empty input
            logger.info(
                f"No order number provided by {caller_number} (timeout or empty input)"
            )

            if language == "de":
                timeout_msg = "Es scheint, als hätten Sie Schwierigkeiten mit der Eingabe. Ich verbinde Sie mit einem Mitarbeiter, der Ihnen helfen kann. Einen Moment bitte."
            else:
                timeout_msg = "It seems you're having trouble with the input. I'm connecting you with a staff member who can help you. Please hold."

            response.say(
                timeout_msg,
                voice=Config.VOICE_NAME,
                voice_engine=(
                    "neural" if Config.VOICE_NAME.startswith("polly.") else "standard"
                ),
            )

            # Log timeout and transfer to manager
            log_conversation(
                call.id, "order_input_timeout_transfer", bot_response=timeout_msg
            )
            update_call_status(call.id, CallStatus.HANDLED)

            # Redirect to manager's phone number
            manager_phone = "+4973929378421"  # 07392 - 93 78 421
            response.dial(number=manager_phone, caller_id=caller_number)

        return Response(str(response), mimetype="text/xml")
        
    except Exception as e:
        logger.error(f"Error handling order: {str(e)}")
        response = VoiceResponse()
        response.say(
            "Sorry, there was an error. Please try again later.",
            voice=Config.VOICE_NAME,
        )
        response.hangup()
        return Response(str(response), mimetype="text/xml")


@app.route("/webhook/order_confirm", methods=["POST"])
def handle_order_confirm():
    """Handle order number confirmation"""
    try:
        # Get the confirmation result (1 for Yes, 2 for No)
        confirmation = request.form.get("Digits", "").strip()
        caller_number = request.form.get("From", "")
        call_sid = request.form.get("CallSid", "")
        
        logger.info(f"Order confirmation from {caller_number}: {confirmation}")
        
        # Get call record
        call = Call.query.filter_by(call_sid=call_sid).first()
        if not call:
            logger.error(f"Call record not found for {call_sid}")
            response = VoiceResponse()
            response.say(
                "Sorry, there was an error. Please try again later.",
                voice=Config.VOICE_NAME,
            )
            response.hangup()
            return Response(str(response), mimetype="text/xml")
        
        # Detect language
        language = detect_language(caller_number)
        
        # Get the order number from the last conversation
        last_conversation = (
            Conversation.query.filter_by(call_id=call.id, step="order_input")
            .order_by(Conversation.timestamp.desc())
            .first()
        )
        
        if not last_conversation:
            logger.error(f"No order input found for call {call_sid}")
            response = VoiceResponse()
            response.say(
                "Sorry, there was an error. Please try again later.",
                voice=Config.VOICE_NAME,
            )
            response.hangup()
            return Response(str(response), mimetype="text/xml")
        
        order_number = last_conversation.user_input
        if not order_number:
            logger.error(f"Order number is empty for call {call_sid}")
        response = VoiceResponse()
            if language == "de":
                error_msg = "Entschuldigung, ich konnte die Rechnungsnummer nicht finden. Bitte versuchen Sie es erneut."
            else:
                error_msg = "Sorry, I couldn't find the order number. Please try again."
            response.say(error_msg, voice=Config.VOICE_NAME)
            response.hangup()
            return Response(str(response), mimetype="text/xml")

        response = VoiceResponse()

        if confirmation == "1":  # Yes - confirmed
            logger.info(f"Order {order_number} confirmed by {caller_number}")
            
            # Log confirmation
            log_conversation(call.id, "order_confirmed", user_input="1")

            # Get real order data from AfterBuy
            order_data = get_order_from_afterbuy(order_number)
            
            # Process confirmed order
            formatted_number = format_order_number_for_speech(order_number)
            if language == "de":
                order_response = f"Vielen Dank! Ich habe Ihre Rechnungsnummer {formatted_number} bestätigt. Ich prüfe den Status für Sie. Bitte warten Sie einen Moment."
            else:
                order_response = f"Thank you! I have confirmed your order number {formatted_number}. I am checking the status for you. Please wait a moment."

            response.say(
                order_response,
                voice=Config.VOICE_NAME,
                voice_engine=(
                    "neural" if Config.VOICE_NAME.startswith("polly.") else "standard"
                ),
            )
            
            # Log order response
            log_conversation(call.id, "order_response", bot_response=order_response)

            # Get real status from AfterBuy
            if order_data:
                # Calculate production and delivery dates FIRST
                order_date = order_data.get("order_date")
                if not order_date:
                    logger.error(f"Order date is missing for order {order_number}")
                    order_date = "18.10.2025 16:27:55"  # Fallback default

                country = order_data.get("buyer", {}).get("country", "DE")
                dates_info = calculate_production_delivery_dates(order_date, country)

                # Add promised delivery date to order_data for overdue checking
                if dates_info and "promised_delivery_date" in dates_info:
                    order_data["promised_delivery_date"] = dates_info[
                        "promised_delivery_date"
                    ]
                else:
                    logger.warning(
                        f"promised_delivery_date not found in dates_info for order {order_number}"
                    )

                # Check if delivery is overdue
                if check_delivery_overdue(order_data):
                    # Delivery is overdue - transfer to manager
                    logger.warning(
                        f"Order {order_number} delivery is overdue, transferring to manager"
                    )

                    overdue_message = get_overdue_delivery_message(language)
                    response.say(
                        overdue_message,
                        voice=Config.VOICE_NAME,
                        voice_engine=(
                            "neural"
                            if Config.VOICE_NAME.startswith("polly.")
                            else "standard"
                        ),
                    )

                    # Log overdue delivery
                    log_conversation(
                        call.id,
                        "overdue_delivery_transfer",
                        bot_response=overdue_message,
                    )
                    update_call_status(call.id, CallStatus.PROBLEM)

                    # Save order to database with overdue status
                    from datetime import datetime

                    promised_date = None
                    if order_data.get("promised_delivery_date"):
                        try:
                            promised_date = datetime.strptime(
                                order_data.get("promised_delivery_date"), "%Y-%m-%d"
                            ).date()
                        except (ValueError, TypeError) as e:
                            logger.error(
                                f"Error parsing promised_delivery_date: {e}, value: {order_data.get('promised_delivery_date')}"
                            )
                            promised_date = None

            order = Order(
                call_id=call.id,
                order_number=order_number,
                        status="Overdue Delivery",
                        notes=f"Order found: {order_data.get('invoice_number', 'N/A')} - Delivery overdue, transferred to manager",
                        promised_delivery_date=promised_date,
            )
                    try:
            db.session.add(order)
            db.session.commit()
                    except Exception as e:
                        logger.error(
                            f"Error saving overdue order to database: {str(e)}"
                        )
                        db.session.rollback()
                        # Continue execution even if database save fails

                    # Redirect to manager's phone number
                    manager_phone = "+4973929378421"  # 07392 - 93 78 421
                    response.dial(number=manager_phone, caller_id=caller_number)

                    return Response(str(response), mimetype="text/xml")
                else:
                    # Normal delivery status
                    status_response = format_order_status_for_speech(
                        order_data, language, dates_info
                    )

                    # Save order to database with normal status
                    from datetime import datetime

                    promised_date = None
                    if order_data.get("promised_delivery_date"):
                        try:
                            promised_date = datetime.strptime(
                                order_data.get("promised_delivery_date"), "%Y-%m-%d"
                            ).date()
                        except (ValueError, TypeError) as e:
                            logger.error(
                                f"Error parsing promised_delivery_date: {e}, value: {order_data.get('promised_delivery_date')}"
                            )
                            promised_date = None

                    order = Order(
                        call_id=call.id,
                        order_number=order_number,
                        status="Found in AfterBuy",
                        notes=f"Order found: {order_data.get('invoice_number', 'N/A')} - {order_data.get('buyer', {}).get('first_name', 'Unknown') if order_data.get('buyer') else 'Unknown'} {order_data.get('buyer', {}).get('last_name', '') if order_data.get('buyer') else ''}",
                        promised_delivery_date=promised_date,
                    )
            else:
                # Order not found in AfterBuy
                if language == "de":
                    status_response = f"Entschuldigung, ich konnte keinen Auftrag mit der Nummer {formatted_number} in unserem System finden. Bitte überprüfen Sie die Nummer oder kontaktieren Sie unseren Kundenservice."
                else:
                    status_response = f"Sorry, I couldn't find an order with number {formatted_number} in our system. Please check the number or contact our customer service."

                # Save order to database as not found
                order = Order(
                    call_id=call.id,
                    order_number=order_number,
                    status="Not Found",
                    notes="Order not found in AfterBuy system",
                )

            try:
                db.session.add(order)
                db.session.commit()
            except Exception as e:
                logger.error(f"Error saving order to database: {str(e)}")
                db.session.rollback()
                # Continue execution even if database save fails
            
            # Simulate processing time
            response.pause(length=2)
            
            # Ensure status_response is not None
            if not status_response:
                logger.error(f"status_response is None for order {order_number}")
                if language == "de":
                    status_response = "Entschuldigung, es ist ein Fehler aufgetreten. Bitte versuchen Sie es später erneut."
                else:
                    status_response = (
                        "Sorry, an error occurred. Please try again later."
                    )

            response.say(
                status_response,
                voice=Config.VOICE_NAME,
                voice_engine=(
                    "neural" if Config.VOICE_NAME.startswith("polly.") else "standard"
                ),
            )
            
            # Log status response
            log_conversation(call.id, "status_response", bot_response=status_response)

            # Ask if they need more help (voice message option)
            if language == "de":
                help_prompt = "Wenn Sie noch Fragen haben, drücken Sie 1 um eine Nachricht zu hinterlassen, oder drücken Sie 2 um mit einem Mitarbeiter verbunden zu werden."
            else:
                help_prompt = "If you have any questions, press 1 to leave a message, or press 2 to speak to a staff member."

            response.say(
                help_prompt,
                voice=Config.VOICE_NAME,
                voice_engine=(
                    "neural" if Config.VOICE_NAME.startswith("polly.") else "standard"
                ),
            )
            
            gather = response.gather(
                input="dtmf",
                timeout=10,
                num_digits=1,
                action="/webhook/voice_message",
                method="POST",
            )
            
            # If no response, say goodbye
            if language == "de":
                response.say(get_goodbye_message(language), voice=Config.VOICE_NAME)
            else:
                response.say(get_goodbye_message(language), voice=Config.VOICE_NAME)
            response.hangup()
            
        elif confirmation == "2":  # No - not confirmed
            logger.info(f"Order {order_number} not confirmed by {caller_number}")
            
            # Log rejection
            log_conversation(call.id, "order_rejected", user_input="2")
            
            # Ask for order number again
            if language == "de":
                retry_response = "Verstanden. Bitte geben Sie Ihre Rechnungsnummer erneut über die Tastatur ein. Drücken Sie die Raute-Taste # wenn Sie fertig sind."
            else:
                retry_response = "Understood. Please enter your order number again using the keypad. Press the hash key # when you are finished."
            
            response.say(
                retry_response,
                voice=Config.VOICE_NAME,
                voice_engine=(
                    "neural" if Config.VOICE_NAME.startswith("polly.") else "standard"
                ),
            )
            
            # Log retry response
            log_conversation(
                call.id, "order_retry_request", bot_response=retry_response
            )
            
            # Ask for order number again
            gather = response.gather(
                input="dtmf",
                timeout=30,
                finishOnKey="#",
                action="/webhook/order",
                method="POST",
            )
            
            # If no response, say goodbye
            if language == "de":
                response.say(get_goodbye_message(language), voice=Config.VOICE_NAME)
            else:
                response.say(get_goodbye_message(language), voice=Config.VOICE_NAME)
            response.hangup()
            
            # Return early - no order to save, no status_response needed
            return Response(str(response), mimetype="text/xml")
            
        else:  # Invalid confirmation
            logger.warning(
                f"Invalid confirmation '{confirmation}' from {caller_number}"
            )
            
            # Log invalid confirmation
            log_conversation(call.id, "invalid_confirmation", user_input=confirmation)
            
            # Ask for confirmation again
            formatted_number = format_order_number_for_speech(order_number)
            if language == "de":
                invalid_response = f"Entschuldigung, ich habe Ihre Antwort nicht verstanden. Sie haben die Rechnungsnummer {formatted_number} eingegeben. Ist das korrekt? Drücken Sie 1 für Ja oder 2 für Nein."
            else:
                invalid_response = f"Sorry, I didn't understand your response. You have entered order number {formatted_number}. Is this correct? Press 1 for Yes or 2 for No."
            
            response.say(
                invalid_response,
                voice=Config.VOICE_NAME,
                voice_engine=(
                    "neural" if Config.VOICE_NAME.startswith("polly.") else "standard"
                ),
            )
            
            # Log invalid response
            log_conversation(
                call.id, "invalid_confirmation_response", bot_response=invalid_response
            )
            
            # Gather confirmation again
            gather = response.gather(
                input="dtmf",
                timeout=10,
                num_digits=1,
                action="/webhook/order_confirm",
                method="POST",
            )
            
            # If no response, say goodbye
            if language == "de":
                response.say(get_goodbye_message(language), voice=Config.VOICE_NAME)
            else:
                response.say(get_goodbye_message(language), voice=Config.VOICE_NAME)
            response.hangup()
        
            # Return early - no order to save, no status_response needed
            return Response(str(response), mimetype="text/xml")

        return Response(str(response), mimetype="text/xml")
        
    except Exception as e:
        logger.error(f"Error handling order confirmation: {str(e)}")
        response = VoiceResponse()
        response.say(
            "Sorry, there was an error. Please try again later.",
            voice=Config.VOICE_NAME,
        )
        response.hangup()
        return Response(str(response), mimetype="text/xml")


@app.route("/webhook/help", methods=["POST"])
def handle_help():
    """Handle additional help requests"""
    try:
        speech_result = request.form.get("SpeechResult", "").lower().strip()
        caller_number = request.form.get("From", "")
        language = detect_language(caller_number)
        
        logger.info(f"Help request from {caller_number}: {speech_result}")
        
        response = VoiceResponse()
        
        # Check if they need more help
        if any(word in speech_result for word in ["ja", "yes", "jawohl", "sure", "ok"]):
            if language == "de":
                help_response = "Gerne! Womit kann ich Ihnen noch helfen? Sie können nach dem Status einer anderen Bestellung fragen oder andere Fragen stellen."
            else:
                help_response = "Of course! How else can I help you? You can ask about the status of another order or ask other questions."
            
            response.say(
                help_response,
                voice=Config.VOICE_NAME,
                voice_engine=(
                    "neural" if Config.VOICE_NAME.startswith("polly.") else "standard"
                ),
            )
            
            # Ask for order number again
            if language == "de":
                order_prompt = "Wenn Sie den Status einer anderen Bestellung erfahren möchten, diktieren Sie bitte die Rechnungsnummer."
            else:
                order_prompt = "If you would like to know the status of another order, please dictate the order number."
            
            # Configure speech recognition with proper language and model
            # Use de-DE format for German (not just "de")
            # Use googlev2_telephony or deepgram_nova-3 for better German support
            speech_language = "de-DE" if language == "de" else "en-US"
            # Use Google STT V2 for better German recognition, or Deepgram Nova-3
            # Note: Check Twilio console to ensure these providers are enabled
            speech_model = "googlev2_telephony"  # Supports de-DE well
            
            gather = response.gather(
                input="speech",
                timeout=10,
                speech_timeout="auto",
                language=speech_language,  # Use de-DE format for proper German recognition
                speech_model=speech_model,  # Use Google STT V2 for better accuracy
                action="/webhook/order",
                method="POST",
            )
            
            # If no response, say goodbye
            if language == "de":
                response.say(get_goodbye_message(language), voice=Config.VOICE_NAME)
            else:
                response.say(get_goodbye_message(language), voice=Config.VOICE_NAME)
            response.hangup()
            
        else:
            # They don't need more help
            if language == "de":
                goodbye_response = get_goodbye_message(language)
            else:
                goodbye_response = get_goodbye_message(language)

            response.say(
                goodbye_response,
                voice=Config.VOICE_NAME,
                voice_engine=(
                    "neural" if Config.VOICE_NAME.startswith("polly.") else "standard"
                ),
            )
            response.hangup()
        
        return Response(str(response), mimetype="text/xml")
        
    except Exception as e:
        logger.error(f"Error handling help: {str(e)}")
        response = VoiceResponse()
        response.say(get_goodbye_message(language), voice=Config.VOICE_NAME)
        response.hangup()
        return Response(str(response), mimetype="text/xml")


@app.route("/health", methods=["GET"])
def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "message": "Voice assistant is running"}


@app.route("/", methods=["GET"])
def dashboard():
    """Dashboard home page"""
    # Get statistics
    total_calls = Call.query.count()
    completed_calls = Call.query.filter_by(status=CallStatus.COMPLETED).count()
    processing_calls = Call.query.filter_by(status=CallStatus.PROCESSING).count()
    problem_calls = Call.query.filter_by(status=CallStatus.PROBLEM).count()
    handled_calls = Call.query.filter_by(status=CallStatus.HANDLED).count()
    
    stats = {
        "total_calls": total_calls,
        "completed_calls": completed_calls,
        "processing_calls": processing_calls,
        "problem_calls": problem_calls,
        "handled_calls": handled_calls,
    }
    
    # Get recent calls
    recent_calls = Call.query.order_by(desc(Call.created_at)).limit(10).all()
    
    return render_template("dashboard.html", stats=stats, recent_calls=recent_calls)


@app.route("/calls", methods=["GET"])
def calls():
    """Calls list page with filtering"""
    page = request.args.get("page", 1, type=int)
    status_filter = request.args.get("status")
    language_filter = request.args.get("language")
    phone_filter = request.args.get("phone")
    
    # Build query
    query = Call.query
    
    if status_filter:
        query = query.filter(Call.status == CallStatus[status_filter])
    
    if language_filter:
        query = query.filter(Call.language == language_filter)
    
    if phone_filter:
        query = query.filter(Call.phone_number.contains(phone_filter))
    
    # Paginate results
    calls = query.order_by(desc(Call.created_at)).paginate(
        page=page, per_page=20, error_out=False
    )
    
    return render_template("calls.html", calls=calls)


@app.route("/calls/<int:call_id>", methods=["GET"])
def call_detail(call_id):
    """Call detail page"""
    call = Call.query.get_or_404(call_id)
    conversations = (
        Conversation.query.filter_by(call_id=call_id)
        .order_by(Conversation.timestamp)
        .all()
    )
    orders = Order.query.filter_by(call_id=call_id).all()
    
    return render_template(
        "call_detail.html", call=call, conversations=conversations, orders=orders
    )


@app.route("/api/calls/<int:call_id>/status", methods=["POST"])
def update_call_status_api(call_id):
    """Update call status via API"""
    try:
        data = request.get_json()
        new_status = data.get("status")
        
        if not new_status or new_status not in [status.name for status in CallStatus]:
            return {"error": "Invalid status"}, 400
        
        call = Call.query.get_or_404(call_id)
        call.status = CallStatus[new_status]
        try:
        db.session.commit()
        logger.info(f"Call {call_id} status updated to {new_status}")
            return {"message": "Status updated successfully", "status": new_status}
        except Exception as db_error:
            logger.error(f"Database error updating call status: {db_error}")
            db.session.rollback()
            return {"error": "Failed to update status"}, 500
        
    except Exception as e:
        logger.error(f"Error updating call status: {e}")
        return {"error": "Failed to update status"}, 500


@app.route("/api/orders/<int:order_id>/status", methods=["POST"])
def update_order_status_api(order_id):
    """Update order status via API"""
    try:
        data = request.get_json()
        new_status = data.get("status")
        notes = data.get("notes", "")
        
        if not new_status:
            return {"error": "Status is required"}, 400
        
        order = Order.query.get_or_404(order_id)
        order.status = new_status
        if notes:
            order.notes = notes
        # Update updated_at timestamp
        order.updated_at = datetime.now(timezone.utc)
        try:
        db.session.commit()
        logger.info(f"Order {order_id} status updated to {new_status}")
            return {
                "message": "Order status updated successfully",
                "status": new_status,
            }
        except Exception as db_error:
            logger.error(f"Database error updating order status: {db_error}")
            db.session.rollback()
            return {"error": "Failed to update order status"}, 500
        
    except Exception as e:
        logger.error(f"Error updating order status: {e}")
        return {"error": "Failed to update order status"}, 500


@app.route("/orders", methods=["GET"])
def orders():
    """Orders list page with filtering"""
    page = request.args.get("page", 1, type=int)
    status_filter = request.args.get("status")
    phone_filter = request.args.get("phone")
    order_number_filter = request.args.get("order_number")
    
    # Build query
    query = Order.query.join(Call)
    
    if status_filter:
        query = query.filter(Order.status == status_filter)
    
    if phone_filter:
        query = query.filter(Call.phone_number.contains(phone_filter))
    
    if order_number_filter:
        query = query.filter(Order.order_number.contains(order_number_filter))
    
    # Paginate results
    orders = query.order_by(desc(Order.created_at)).paginate(
        page=page, per_page=20, error_out=False
    )
    
    return render_template("orders.html", orders=orders)


@app.route("/orders/<int:order_id>", methods=["GET"])
def order_detail(order_id):
    """Order detail page"""
    order = Order.query.get_or_404(order_id)
    return render_template("order_detail.html", order=order)


@app.route("/webhook/voice_message", methods=["POST"])
def handle_voice_message():
    """Handle voice message choice (1 = leave message, 2 = end call)"""
    try:
        digits = request.form.get("Digits", "").strip()
        caller_number = request.form.get("From", "")
        call_sid = request.form.get("CallSid", "")

        logger.info(f"Voice message choice from {caller_number}: {digits}")

        # Get call record
        call = Call.query.filter_by(call_sid=call_sid).first()
        if not call:
            logger.error(f"Call record not found for {call_sid}")
            response = VoiceResponse()
            response.say(
                "Sorry, there was an error. Please try again later.",
                voice=Config.VOICE_NAME,
            )
            response.hangup()
            return Response(str(response), mimetype="text/xml")

        # Use language from call record (more reliable than re-detecting)
        language = call.language if call.language else detect_language(caller_number)
        logger.info(f"Using language for transcription: {language} (from call record)")

        response = VoiceResponse()

        if digits == "1":  # User wants to leave a voice message
            logger.info(f"User {caller_number} wants to leave a voice message")

            if language == "de":
                message_prompt = "Bitte hinterlassen Sie nach dem Signalton eine Nachricht. Drücken Sie die Raute-Taste # wenn Sie fertig sind. Sie erhalten innerhalb von 24 Stunden eine Antwort per E-Mail."
            else:
                message_prompt = "Please leave a message after the tone. Press the hash key # when you are finished. You will receive a reply by email within 24 hours."

            response.say(
                message_prompt,
                voice=Config.VOICE_NAME,
                voice_engine=(
                    "neural" if Config.VOICE_NAME.startswith("polly.") else "standard"
                ),
            )

            # Record the message with transcription
            # finishOnKey="#" allows user to press # to end recording
            # timeout=5 automatically ends recording after 5 seconds of silence
            # IMPORTANT: Twilio's built-in transcription for <Record> ONLY supports English (en-US)
            # Even if you set transcribeLanguage="de-DE", Twilio will transcribe German as English
            # This is a known limitation of Twilio's transcription service
            #
            # Solutions:
            # 1. Use external transcription service (Google Cloud Speech-to-Text, Deepgram, etc.)
            #    - Download audio from recording_url in recordingStatusCallback
            #    - Send to external service with de-DE language code
            #    - Update transcription in database
            # 2. Use Twilio Add-ons (IBM Watson, etc.) that support German
            # 3. For now, we keep transcribe=True but expect English transcription for German audio
            #
            # For proper German transcription, implement external service integration
            transcription_language = "de-DE" if language == "de" else "en-US"
            logger.warning(
                f"Setting transcription language to: {transcription_language}, "
                f"but Twilio built-in transcription may not support German properly. "
                f"Consider using external transcription service for accurate German transcription."
            )

            # The <Record> verb uses transcribeLanguage parameter for transcription
            # WARNING: Twilio's built-in transcription only fully supports en-US
            # German audio will be transcribed poorly or as English
            response.record(
                maxLength=60,  # 60 seconds max
                action="/webhook/recorded",
                method="POST",
                finishOnKey="#",  # User can press # to finish recording
                timeout=5,  # Auto-finish after 5 seconds of silence
                recordingStatusCallback="/webhook/recording_status",
                transcribe=True,  # Enable transcription (but limited to English quality)
                transcribeCallback="/webhook/transcription",  # Callback for transcription
                transcribeLanguage=transcription_language,  # Set language (may not work for German)
            )

            # Log action
            log_conversation(
                call.id, "voice_message_request", bot_response=message_prompt
            )

        elif digits == "2":  # User wants to speak to manager
            logger.info(f"User {caller_number} wants to speak to manager")

            if language == "de":
                transfer_msg = "Ich verbinde Sie jetzt mit einem unserer Mitarbeiter. Einen Moment bitte."
            else:
                transfer_msg = (
                    "I'm now connecting you with one of our staff. Please hold."
                )

            response.say(
                transfer_msg,
                voice=Config.VOICE_NAME,
                voice_engine=(
                    "neural" if Config.VOICE_NAME.startswith("polly.") else "standard"
                ),
            )

            # Redirect to manager's phone number
            manager_phone = "+4973929378421"  # 07392 - 93 78 421
            response.dial(number=manager_phone, caller_id=caller_number)

            # Log action
            log_conversation(call.id, "transfer_to_manager", bot_response=transfer_msg)

        else:  # Invalid choice
            logger.warning(
                f"Invalid voice message choice '{digits}' from {caller_number}"
            )

            if language == "de":
                error_msg = "Entschuldigung, ich habe Ihre Antwort nicht verstanden. Wenn Sie noch Fragen haben, drücken Sie 1. Um mit einem Mitarbeiter verbunden zu werden, drücken Sie 2."
            else:
                error_msg = "Sorry, I didn't understand your response. If you have questions, press 1. To speak to a staff member, press 2."

            response.say(
                error_msg,
                voice=Config.VOICE_NAME,
                voice_engine=(
                    "neural" if Config.VOICE_NAME.startswith("polly.") else "standard"
                ),
            )

            gather = response.gather(
                input="dtmf",
                timeout=10,
                num_digits=1,
                action="/webhook/voice_message",
                method="POST",
            )

            # Fallback
            if language == "de":
                response.say(get_goodbye_message(language), voice=Config.VOICE_NAME)
            else:
                response.say(get_goodbye_message(language), voice=Config.VOICE_NAME)
            response.hangup()

        return Response(str(response), mimetype="text/xml")

    except Exception as e:
        logger.error(f"Error handling voice message: {str(e)}")
        response = VoiceResponse()
        response.say(
            "Sorry, there was an error. Please try again later.",
            voice=Config.VOICE_NAME,
        )
        response.hangup()
        return Response(str(response), mimetype="text/xml")


@app.route("/webhook/recorded", methods=["POST"])
def handle_recorded():
    """Handle recorded voice message"""
    try:
        recording_url = request.form.get("RecordingUrl", "")
        recording_sid = request.form.get("RecordingSid", "")
        recording_duration = request.form.get("RecordingDuration", "0")
        recording_status = request.form.get("RecordingStatus", "")
        digits = request.form.get("Digits", "")  # Will contain "#" if user pressed #
        recording_transcription = request.form.get(
            "RecordingTranscription", ""
        ) or request.form.get("TranscriptionText", "")
        caller_number = request.form.get("From", "")
        call_sid = request.form.get("CallSid", "")

        # Determine how recording was finished
        try:
            duration_seconds = int(recording_duration) if recording_duration else 0
        except (ValueError, TypeError):
            duration_seconds = 0

        finish_method = "unknown"
        if digits == "#":
            finish_method = "user_pressed_hash"
        elif duration_seconds >= 60:
            finish_method = "max_length_reached"
        elif duration_seconds > 0:
            finish_method = "timeout_silence"

        logger.info(f"Voice message recorded from {caller_number}")
        logger.info(f"Recording URL: {recording_url}")
        logger.info(f"Recording Duration: {duration_seconds} seconds")
        logger.info(f"Recording finished by: {finish_method}")
        logger.info(f"Recording Transcription: {recording_transcription}")

        # Get call record
        call = Call.query.filter_by(call_sid=call_sid).first()
        if call:
            # Save recording transcription text to conversation
            # Use language from call record for consistency
            language = (
                call.language if call.language else detect_language(caller_number)
            )

            # Check if recording is empty or too short
            if duration_seconds < 1 or not recording_url:
                # Recording is too short or failed
                if language == "de":
                    thank_you = "Entschuldigung, ich konnte Ihre Nachricht nicht aufnehmen. Bitte versuchen Sie es erneut oder kontaktieren Sie uns direkt."
                else:
                    thank_you = "Sorry, I couldn't record your message. Please try again or contact us directly."

                logger.warning(
                    f"Recording failed or too short: duration={duration_seconds}s, url={recording_url}"
                )
            else:
                if language == "de":
                    thank_you = "Vielen Dank für Ihre Nachricht. Wir melden uns innerhalb von 24 Stunden bei Ihnen. Auf Wiedersehen!"
                else:
                    thank_you = "Thank you for your message. We will contact you within 24 hours. Goodbye!"

            # Save the transcription text with URL always included
            # This ensures URL is available for handle_transcription later
            if duration_seconds >= 1 and recording_url:
                # Always include URL in user_input, even if transcription is available
                # Format: "Voice message recorded (Duration: Xs, Finished by: Y, URL: Z)"
                # If transcription is available, it will be appended in handle_transcription
                base_message = f"Voice message recorded (Duration: {duration_seconds}s, Finished by: {finish_method}, URL: {recording_url})"
                if recording_transcription:
                    # Include transcription in the initial message
                    transcription_text = (
                        f"{base_message}\nTranscription: {recording_transcription}"
                    )
                else:
                    transcription_text = base_message
            else:
                transcription_text = (
                    f"Voice message recording failed (Duration: {duration_seconds}s)"
                )

            log_conversation(
                call.id,
                "voice_message_recorded",
                user_input=transcription_text,
                bot_response=thank_you,
            )

            # Also save to order notes (only if recording was successful)
            order_number = None
            if duration_seconds >= 1 and recording_url:
                orders = (
                    Order.query.filter_by(call_id=call.id)
                    .order_by(Order.created_at.desc())
                    .all()
                )
                if orders:
                    order = orders[0]
                    order_number = order.order_number
                    message_info = f"Voice message (Duration: {duration_seconds}s, Finished by: {finish_method})"
                    if recording_transcription:
                        message_info += f": {recording_transcription}"
                    if order.notes:
                        order.notes += f"\n\n{message_info}"
                    else:
                        order.notes = message_info
                    db.session.commit()

            # Note: Email will be sent in handle_transcription() when full transcription is available
            # This prevents duplicate emails and ensures we send email with complete transcription
            # IMPORTANT: Do NOT send email here even if transcription is available
            # This prevents rate limiting issues - email will be sent only once in handle_transcription()
            # The transcription from handle_recorded might be incomplete or preliminary
            email_already_sent = Conversation.query.filter_by(
                call_id=call.id, step="email_sent"
            ).first()

            logger.info(
                f"handle_recorded: duration={duration_seconds}, recording_url={'present' if recording_url else 'missing'}, "
                f"transcription={'present' if recording_transcription else 'missing'}, email_already_sent={email_already_sent is not None}"
            )

            # Always skip email sending in handle_recorded to avoid rate limiting
            # Email will be sent only once in handle_transcription() with full transcription
            if email_already_sent:
                logger.info(
                    f"Email already sent for call {call_sid}, skipping duplicate"
                )
            else:
                # Email will be sent in handle_transcription() when full transcription arrives
                logger.info(
                    f"Email will be sent in handle_transcription() when full transcription is available for call {call_sid}"
                )

            update_call_status(call.id, CallStatus.COMPLETED)

            response = VoiceResponse()
            response.say(
                thank_you,
                voice=Config.VOICE_NAME,
                voice_engine=(
                    "neural" if Config.VOICE_NAME.startswith("polly.") else "standard"
                ),
            )
            response.hangup()
        else:
            # Call not found - use default language
            language = detect_language(caller_number) if caller_number else "de"
            response = VoiceResponse()
            response.say(get_goodbye_message(language), voice=Config.VOICE_NAME)
            response.hangup()

        return Response(str(response), mimetype="text/xml")

    except Exception as e:
        logger.error(f"Error handling recorded message: {str(e)}")
        response = VoiceResponse()
        response.say("Thank you for your message. Goodbye!", voice=Config.VOICE_NAME)
        response.hangup()
        return Response(str(response), mimetype="text/xml")


@app.route("/webhook/transcription", methods=["POST"])
def handle_transcription():
    """Handle transcription callback from Twilio"""
    try:
        transcription_text = request.form.get("TranscriptionText", "")
        transcription_status = request.form.get("TranscriptionStatus", "")
        call_sid = request.form.get("CallSid", "")
        recording_sid = request.form.get("RecordingSid", "")

        logger.info(
            f"Transcription received: Status={transcription_status}, Text='{transcription_text[:100]}...'"
        )

        # Get call record
        call = Call.query.filter_by(call_sid=call_sid).first()
        if not call:
            logger.warning(
                f"Call record not found for {call_sid} in handle_transcription"
            )
            return Response(status=200)

        if not transcription_text:
            logger.warning(f"Transcription text is empty for call {call_sid}")
            return Response(status=200)

        logger.info(
            f"Processing transcription for call {call_sid}, call_id: {call.id}, transcription length: {len(transcription_text)}"
        )

        if call and transcription_text:
            # Update the conversation with transcription text
            conversations = (
                Conversation.query.filter_by(
                    call_id=call.id, step="voice_message_recorded"
                )
                .order_by(Conversation.timestamp.desc())
                .all()
            )

            if conversations:
                conversation = conversations[0]
                # Preserve existing user_input (which contains URL) and append transcription
                # Format: "Voice message recorded (Duration: Xs, Finished by: Y, URL: Z)\nTranscription: ..."
                existing_input = conversation.user_input or ""
                if "URL:" in existing_input and "Transcription:" not in existing_input:
                    # Keep the URL part and append transcription
                    conversation.user_input = (
                        f"{existing_input}\nTranscription: {transcription_text}"
                    )
                elif "Transcription:" in existing_input:
                    # Update existing transcription
                    # Replace old transcription with new one
                    lines = existing_input.split("\n")
                    new_lines = []
                    for line in lines:
                        if line.startswith("Transcription:"):
                            new_lines.append(f"Transcription: {transcription_text}")
                        else:
                            new_lines.append(line)
                    conversation.user_input = "\n".join(new_lines)
                else:
                    # If no URL in existing input, just set transcription
                    conversation.user_input = transcription_text
                db.session.commit()
                logger.info(
                    f"Updated conversation {conversation.id} with transcription text"
                )

            # Also update order notes
            order_number = None
            orders = (
                Order.query.filter_by(call_id=call.id)
                .order_by(Order.created_at.desc())
                .all()
            )
            if orders:
                order = orders[0]
                order_number = order.order_number
                if order.notes:
                    order.notes = order.notes.replace(
                        "Voice message: Voice message recorded (URL:",
                        f"Voice message transcription: {transcription_text}",
                    )
                else:
                    order.notes = f"Voice message transcription: {transcription_text}"
                db.session.commit()

            # Get recording URL from conversation to send updated email with full transcription
            recording_url = None
            conversations_with_url = (
                Conversation.query.filter_by(
                    call_id=call.id, step="voice_message_recorded"
                )
                .order_by(Conversation.timestamp.desc())
                .all()
            )
            logger.info(
                f"Found {len(conversations_with_url)} conversations with step 'voice_message_recorded' for call {call_sid}"
            )
            for conv in conversations_with_url:
                if conv.user_input:
                    logger.debug(
                        f"Checking conversation {conv.id} user_input for URL: {conv.user_input[:200]}"
                    )
                    # Try to extract URL from user_input in different formats
                    # Format 1: "URL: https://..."
                    url_match = re.search(r"URL:\s*([^\s\)\n]+)", conv.user_input)
                    if url_match:
                        recording_url = url_match.group(1)
                        logger.info(
                            f"Found recording URL using Format 1: {recording_url}"
                        )
                        break
                    # Format 2: "Voice message URL: https://..." (from recording_status callback)
                    url_match2 = re.search(
                        r"Voice message URL:\s*([^\s\n]+)", conv.user_input
                    )
                    if url_match2:
                        recording_url = url_match2.group(1)
                        break
                    # Format 3: Direct URL pattern (http:// or https://)
                    url_match3 = re.search(r"(https?://[^\s\)\n]+)", conv.user_input)
                    if url_match3:
                        potential_url = url_match3.group(1)
                        # Validate it looks like a Twilio recording URL
                        if (
                            "api.twilio.com" in potential_url
                            or "recordings" in potential_url.lower()
                        ):
                            recording_url = potential_url
                            break

            # If still no URL, try to get it from handle_recorded data stored in conversation
            # The URL should be in the conversation from handle_recorded
            if not recording_url:
                # Look for URL in all conversations for this call
                all_conversations = (
                    Conversation.query.filter_by(call_id=call.id)
                    .order_by(Conversation.timestamp.desc())
                    .all()
                )
                for conv in all_conversations:
                    if conv.user_input:
                        # Try multiple URL patterns
                        patterns = [
                            r"URL:\s*([^\s\)\n]+)",  # URL: https://...
                            r"Voice message URL:\s*([^\s\n]+)",  # Voice message URL: https://...
                            r"(https?://api\.twilio\.com/[^\s\)\n]+)",  # Direct Twilio URL
                        ]
                        for pattern in patterns:
                            url_match = re.search(pattern, conv.user_input)
                            if url_match:
                                potential_url = url_match.group(1)
                                # Clean up URL (remove trailing punctuation)
                                potential_url = potential_url.rstrip(".,;:!?)")
                                if potential_url.startswith("http"):
                                    recording_url = potential_url
                                    logger.info(
                                        f"Found recording URL in conversation: {recording_url}"
                                    )
                                    break
                        if recording_url:
                            break

            if not recording_url:
                # Log detailed information for debugging
                logger.warning(
                    f"Could not find recording_url for call {call_sid} in any conversation. "
                    f"Available conversations: {[c.step for c in conversations_with_url]}"
                )
                # Log user_input from conversations for debugging
                for conv in conversations_with_url:
                    if conv.user_input:
                        logger.warning(
                            f"Conversation {conv.id} user_input (first 300 chars): {conv.user_input[:300]}"
                        )

            # Check if email was already sent for this call to avoid duplicates
            # This prevents rate limiting issues from sending multiple emails
            email_already_sent = Conversation.query.filter_by(
                call_id=call.id, step="email_sent"
            ).first()

            if email_already_sent:
                logger.info(
                    f"Email already sent for call {call_sid}, skipping to avoid duplicates and rate limiting"
                )
                return Response(status=200)

            # Check for recent email attempts to prevent rate limiting
            # SMTP server may block for 30+ seconds, so we check last 120 seconds to be safe
            # This prevents both failed attempts and too frequent successful sends
            recent_attempt_threshold = datetime.now(timezone.utc) - timedelta(seconds=120)

            # Check for any recent email activity (both attempts and successful sends)
            recent_email_activity = (
                Conversation.query.filter(
                    Conversation.call_id == call.id,
                    Conversation.step.in_(["email_attempt", "email_sent"]),
                    Conversation.timestamp >= recent_attempt_threshold,
                )
                .order_by(Conversation.timestamp.desc())
                .first()
            )

            if recent_email_activity:
                time_since_last = (
                    datetime.now(timezone.utc) - recent_email_activity.timestamp
                ).total_seconds()
                logger.warning(
                    f"Recent email activity detected for call {call_sid} "
                    f"({int(time_since_last)} seconds ago, step: {recent_email_activity.step}). "
                    f"Skipping to avoid SMTP rate limiting. Last activity: {recent_email_activity.timestamp}"
                )
                return Response(status=200)

            # Send email with full transcription (primary email sending point)
            # This is the main place where email is sent to avoid duplicates
            logger.info(
                f"handle_transcription: Checking conditions for email sending - "
                f"transcription_text={'present' if transcription_text else 'missing'}, "
                f"recording_url={'present' if recording_url else 'missing'}"
            )
            if transcription_text and recording_url:
                try:
                    # Get caller number and language from call
                    caller_number = call.phone_number if call else ""
                    language = call.language if call and call.language else "de"

                    # Validate required fields
                    if not caller_number or not recording_url:
                        logger.warning(
                            f"Cannot send email: missing caller_number or recording_url for call {call_sid}"
                        )
                        return Response(status=200)

                    # Get duration from conversation if available
                    duration_seconds = 0
                    if conversations_with_url and len(conversations_with_url) > 0:
                        duration_match = re.search(
                            r"Duration:\s*(\d+)",
                            conversations_with_url[0].user_input or "",
                        )
                        if duration_match:
                            try:
                                duration_seconds = int(duration_match.group(1))
                            except (ValueError, TypeError):
                                duration_seconds = 0

                    # Send email with full transcription
                    email_sent = send_voice_message_email(
                        caller_number=caller_number,
                        recording_url=recording_url,
                        transcription_text=transcription_text,
                        duration_seconds=duration_seconds,
                        language=language,
                        order_number=order_number,
                    )
                    if email_sent:
                        logger.info(
                            f"Successfully sent email with transcription for call {call_sid} "
                            f"(duration: {duration_seconds}s, order: {order_number or 'N/A'})"
                        )
                        # Mark that email was sent to avoid duplicates
                        log_conversation(
                            call.id,
                            "email_sent",
                            user_input=f"Email sent to {Config.MAIL_RECIPIENT}",
                        )
                    else:
                        # Email sending failed (possibly due to rate limiting)
                        # Log the attempt to prevent too frequent retries
                        logger.warning(
                            f"Email sending returned False for call {call_sid} - check logs for details. "
                            f"This may be due to SMTP rate limiting."
                        )
                        # Log the attempt (but not as "sent") to track and prevent too frequent retries
                        log_conversation(
                            call.id,
                            "email_attempt",
                            user_input=f"Email sending failed for call {call_sid} - may be rate limited",
                        )
                except Exception as e:
                    logger.error(
                        f"Failed to send email with transcription: {str(e)}",
                        exc_info=True,
                    )
            else:
                # Missing transcription or recording URL - log warning
                if not transcription_text:
                    logger.warning(
                        f"Cannot send email: transcription_text is empty for call {call_sid}"
                    )
                if not recording_url:
                    logger.warning(
                        f"Cannot send email: recording_url is missing for call {call_sid}"
                    )

        return Response(status=200)

    except Exception as e:
        logger.error(f"Error handling transcription: {str(e)}")
        return Response(status=500)


@app.route("/webhook/recording_status", methods=["POST"])
def handle_recording_status():
    """Handle recording status callback"""
    try:
        recording_url = request.form.get("RecordingUrl", "")
        recording_sid = request.form.get("RecordingSid", "")
        recording_status = request.form.get("RecordingStatus", "")
        call_sid = request.form.get("CallSid", "")

        logger.info(f"Recording status: {recording_status}, URL: {recording_url}")

        # Get call record and save recording info
        call = Call.query.filter_by(call_sid=call_sid).first()
        if call and recording_status == "completed" and recording_url:
            # If external transcription service is configured, use it for accurate German transcription
            # This bypasses Twilio's limited transcription support
            if Config.TRANSCRIPTION_SERVICE in ["google", "deepgram"]:
                try:
                    from transcription_service import transcribe_with_external_service

                    language = call.language if call.language else "de"
                    transcription_language = "de-DE" if language == "de" else "en-US"

                    logger.info(
                        f"Using external transcription service ({Config.TRANSCRIPTION_SERVICE}) "
                        f"for accurate {transcription_language} transcription"
                    )

                    # Transcribe with external service
                    external_transcription = transcribe_with_external_service(
                        audio_url=recording_url,
                        language=transcription_language,
                        service=Config.TRANSCRIPTION_SERVICE,
                    )

                    if external_transcription:
                        logger.info(
                            f"External transcription successful: {len(external_transcription)} chars"
                        )
                        # Update conversation with external transcription
                        log_conversation(
                            call.id,
                            "voice_message_recorded",
                            user_input=f"External transcription ({Config.TRANSCRIPTION_SERVICE}): {external_transcription}",
                        )
                        # Update order notes
                        orders = (
                            Order.query.filter_by(call_id=call.id)
                            .order_by(Order.created_at.desc())
                            .all()
                        )
                        if orders:
                            order = orders[0]
                            if order.notes:
                                order.notes += f"\nExternal transcription ({Config.TRANSCRIPTION_SERVICE}): {external_transcription}"
                            else:
                                order.notes = f"External transcription ({Config.TRANSCRIPTION_SERVICE}): {external_transcription}"
                            db.session.commit()
                    else:
                        logger.warning(
                            "External transcription returned no result, falling back to Twilio"
                        )
                except ImportError:
                    logger.warning(
                        f"External transcription service ({Config.TRANSCRIPTION_SERVICE}) not available, "
                        f"falling back to Twilio transcription"
                    )
                except Exception as e:
                    logger.error(f"External transcription error: {e}", exc_info=True)

            # Update order notes with recording info
            orders = (
                Order.query.filter_by(call_id=call.id)
                .order_by(Order.created_at.desc())
                .all()
            )
            if orders:
                order = orders[0]
                if order.notes:
                    order.notes += f"\nVoice message URL: {recording_url}"
                else:
                    order.notes = f"Voice message URL: {recording_url}"
                db.session.commit()

        return Response(status=200)

    except Exception as e:
        logger.error(f"Error handling recording status: {str(e)}")
        return Response(status=500)


@app.route("/api/health", methods=["GET"])
def api_health():
    """API health check"""
    return {
        "message": "Voice Assistant with Database",
        "endpoints": {
            "webhook": "/webhook/voice",
            "health": "/api/health",
            "dashboard": "/",
        },
    }


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=Config.FLASK_DEBUG, host="0.0.0.0", port=5001)
