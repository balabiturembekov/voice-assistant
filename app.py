from flask import Flask, request, Response, render_template
from twilio.twiml.voice_response import VoiceResponse
import logging
from config import Config
from models import db, Call, Conversation, Order, CallStatus
from sqlalchemy import desc
from afterbuy_client import AfterbuyClient
from services import (
    detect_language, get_greeting_message, 
    format_order_number_for_speech, 
    get_goodbye_message,
)


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config.from_object(Config)

# Initialize database
db.init_app(app)


def create_or_get_call(call_sid, phone_number, language):
    """Create or get existing call record"""
    call = Call.query.filter_by(call_sid=call_sid).first()
    if not call:
        call = Call(
            call_sid=call_sid,
            phone_number=phone_number,
            language=language,
            status=CallStatus.PROCESSING
        )
        db.session.add(call)
        db.session.commit()
        logger.info(f"Created new call record: {call_sid}")
    return call

def log_conversation(call_id, step, user_input=None, bot_response=None):
    """Log conversation step"""
    conversation = Conversation(
        call_id=call_id,
        step=step,
        user_input=user_input,
        bot_response=bot_response
    )
    db.session.add(conversation)
    db.session.commit()
    logger.info(f"Logged conversation: {step}")

def update_call_status(call_id, status):
    """Update call status"""
    call = Call.query.get(call_id)
    if call:
        call.status = status
        db.session.commit()
        logger.info(f"Updated call {call_id} status to {status.value}")


def validate_order_number(order_text, language='de'):
    """Validate if the input looks like a real order number"""
    if not order_text or len(order_text.strip()) < 2:
        return False, "too_short"
    
    order_text = order_text.strip().lower()
    
    # Common non-order words that might be misrecognized
    non_order_words = [
        # Entertainment
        'dry', 'season', 'episode', 'movie', 'film', 'series', 'show',
        'lexington', 'drive', 'street', 'avenue', 'road', 'boulevard',
        'trocken', 'saison', 'episode', 'film', 'serie', 'show',
        'straße', 'weg', 'allee', 'platz', 'gasse',
        
        # Greetings and responses
        'hello', 'hi', 'yes', 'no', 'okay', 'ok', 'sure', 'maybe',
        'hallo', 'ja', 'nein', 'okay', 'ok', 'sicher', 'vielleicht',
        
        # Service words
        'help', 'support', 'service', 'information', 'question',
        'hilfe', 'support', 'service', 'information', 'frage',
        
        # Common words that are not order numbers
        'the', 'and', 'or', 'but', 'with', 'from', 'to', 'for',
        'der', 'die', 'das', 'und', 'oder', 'aber', 'mit', 'von', 'zu', 'für',
        
        # Address components
        'street', 'avenue', 'road', 'boulevard', 'lane', 'court',
        'straße', 'weg', 'allee', 'platz', 'gasse', 'hof'
    ]
    
    # Check if it contains non-order words (but allow partial matches in longer strings)
    for word in non_order_words:
        if word in order_text:
            # If the text is mostly the non-order word, reject it
            if len(word) >= len(order_text) * 0.5:  # Word is at least 50% of the text
                return False, "contains_non_order_words"
            # If it's a longer string with numbers/patterns, it might be valid
            elif not any(char.isdigit() for char in order_text) and not any(pattern in order_text for pattern in ['-', '_', '.']):
                return False, "contains_non_order_words"
    
    # Check if it's mostly letters without numbers (suspicious)
    if order_text.isalpha() and len(order_text) > 10:
        return False, "too_many_letters"
    
    # Check if it contains at least some numbers or common order patterns
    has_numbers = any(char.isdigit() for char in order_text)
    has_common_patterns = any(pattern in order_text for pattern in ['-', '_', '.', ' '])
    
    if not has_numbers and not has_common_patterns:
        return False, "no_numbers_or_patterns"
    
    # If it passes all checks, it might be a valid order number
    return True, "valid"

def get_consent_prompts(language):
    """Get consent prompts for different languages"""
    prompts = {
        'de': {
            'yes': 'Drücken Sie 1 für Ja oder 2 für Nein.',
            'yes_option': '1',
            'no_option': '2'
        },
        'en': {
            'yes': 'Press 1 for Yes or 2 for No.',
            'yes_option': '1',
            'no_option': '2'
        }
    }
    
    return prompts.get(language, prompts['de'])  # Default to German

def get_order_from_afterbuy(order_id):
    """
    Get order data from AfterBuy API
    
    Args:
        order_id: The order ID to look up
        
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
            user_password=Config.AFTERBUY_USER_PASSWORD
        )
        
        # Get order data
        order_data = afterbuy_client.get_order_by_id(order_id)
        
        if order_data:
            logger.info(f"Successfully retrieved order {order_id} from AfterBuy")
            return order_data
        else:
            logger.warning(f"Order {order_id} not found in AfterBuy")
            return None
            
    except Exception as e:
        logger.error(f"Error retrieving order {order_id} from AfterBuy: {str(e)}")
        return None

def calculate_production_delivery_dates(order_date_str, country_code='DE'):
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
        # Parse order date
        order_date = datetime.strptime(order_date_str.split()[0], '%d.%m.%Y')
        
        # Production weeks based on country (from bot_messages.txt)
        production_weeks = {
            'TR': (6, 10),   # Turkey: 6-10 weeks
            'CN': (8, 12),   # China: 8-12 weeks
            'PL': (4, 8),    # Poland: 4-8 weeks
            'IT': (4, 8),    # Italy: 4-8 weeks
            'DE': (8, 12),   # Germany (default): 8-12 weeks
        }
        
        weeks = production_weeks.get(country_code, (8, 12))
        
        # Calculate production time
        production_start = order_date + timedelta(days=7)  # Production starts 1 week after order
        
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
            'order_date': order_date.strftime('%d.%m.%Y'),
            'order_date_formatted': order_date.strftime('%d.%m.%Y'),
            'production_start_date': production_start.strftime('%d.%m.%Y'),
            'production_min_weeks': production_min_weeks,
            'production_max_weeks': production_max_weeks,
            'delivery_week': delivery_week,
            'delivery_year': year,
            'delivery_date_start': (delivery_date - timedelta(days=3)).strftime('%d.%m.%Y'),
            'delivery_date_end': (delivery_date + timedelta(days=3)).strftime('%d.%m.%Y'),
        }
    except Exception as e:
        logger.error(f"Error calculating dates: {e}")
        return {
            'order_date': order_date_str,
            'production_start_date': '22.10.2025',
            'production_min_weeks': 6,
            'production_max_weeks': 10,
            'delivery_week': 42,
            'delivery_year': 2025,
            'delivery_date_start': '13.10.2025',
            'delivery_date_end': '19.10.2025',
        }


def format_order_status_for_speech(order_data, language='de'):
    """
    Format order status information for speech output
    
    Args:
        order_data: Dictionary with order data from AfterBuy
        language: Language code ('de' or 'en')
        
    Returns:
        Formatted string for speech
    """
    if not order_data:
        if language == 'de':
            return "Entschuldigung, ich konnte keine Informationen zu diesem Auftrag finden."
        else:
            return "Sorry, I couldn't find any information about this order."
    
    # Parse memo for additional info
    memo_data = {}
    if 'memo' in order_data and order_data['memo']:
        from afterbuy_client import AfterbuyClient
        temp_client = AfterbuyClient('', '', '', '', '')
        memo_data = temp_client.parse_memo(order_data['memo'])
    
    # Get payment info
    payment_info = order_data.get('payment', {})
    already_paid = payment_info.get('already_paid', '0,00')
    full_amount = payment_info.get('full_amount', '0,00')
    
    # Get buyer info
    buyer_info = order_data.get('buyer', {})
    customer_name = buyer_info.get('first_name', '')
    country = buyer_info.get('country', 'DE')
    
    # Get order date
    order_date = order_data.get('order_date', '18.10.2025 16:27:55')
    
    # Get payment date (when order was processed)
    payment_date = order_data.get('payment', {}).get('payment_date', order_date)
    
    # Calculate production and delivery dates
    dates_info = calculate_production_delivery_dates(order_date, country)
    
    # Format amounts (remove commas for speech)
    # AfterBuy uses commas as thousand separators, so we need to handle this properly
    already_paid_clean = already_paid.replace(',', '')
    full_amount_clean = full_amount.replace(',', '')
    
    # Convert to proper format for speech (e.g., 1680 instead of 168000)
    try:
        # Parse the original amounts correctly
        already_paid_parsed = float(already_paid.replace(',', '.'))
        full_amount_parsed = float(full_amount.replace(',', '.'))
        
        # Format for speech (remove decimal if it's .00)
        already_paid_clean = str(int(already_paid_parsed)) if already_paid_parsed == int(already_paid_parsed) else str(already_paid_parsed)
        full_amount_clean = str(int(full_amount_parsed)) if full_amount_parsed == int(full_amount_parsed) else str(full_amount_parsed)
    except:
        pass
    
    if language == 'de':
        # Format order ID for speech
        order_id = order_data.get('order_id', 'unbekannt')
        order_id_formatted = format_order_number_for_speech(order_id)
        
        status_text = f"""Ihr Auftrag {order_id_formatted}:
Sie haben für Ihren Auftrag insgesamt {already_paid_clean} Euro bezahlt.
Der gesamte Rechnungsbetrag beträgt {full_amount_clean} Euro.

Der Auftrag wurde durch den Kunden {customer_name} erteilt.
Ihr Auftrag wurde am {dates_info['order_date_formatted']} angenommen und am {dates_info['production_start_date']} an die Produktion übergeben.

Ihre Ware befindet sich derzeit in der Produktion und hat eine voraussichtliche Lieferzeit von {dates_info['production_min_weeks']} bis {dates_info['production_max_weeks']} Wochen.

Wir erwarten die Lieferung in der Kalenderwoche {dates_info['delivery_week']}/{dates_info['delivery_year']}, also in der Woche vom {dates_info['delivery_date_start']} bis {dates_info['delivery_date_end']}.

Wir freuen uns, Ihnen ein hochwertiges Produkt liefern zu dürfen,
und halten Sie selbstverständlich über den weiteren Verlauf auf dem Laufenden."""
        
    else:
        status_text = f"The status of your order {order_data.get('order_id', 'unknown')} is: "
        
        if memo_data.get('amount_value', 0) > 0:
            status_text += f"{already_paid_clean} Euros have been paid out of {full_amount_clean} Euros total. "
            if memo_data.get('payment_percent'):
                status_text += f"This represents a {memo_data['payment_percent']} percent down payment. "
        
        if customer_name:
            status_text += f"The order was placed by {customer_name}. "
        
        status_text += "You will receive an email with further details."
    
    return status_text


@app.route('/webhook/voice', methods=['POST'])
def handle_incoming_call():
    """Handle incoming voice calls"""
    try:
        # Get caller information
        caller_number = request.form.get('From', '')
        call_sid = request.form.get('CallSid', '')
        logger.info(f"Incoming call from: {caller_number}")
        
        # Detect language
        language = detect_language(caller_number)
        logger.info(f"Detected language: {language}")
        
        # Create or get call record
        call = create_or_get_call(call_sid, caller_number, language)
        
        # Create TwiML response
        response = VoiceResponse()
        
        # Use static greeting text
        if language == 'de':
            #greeting = "Hallo, Sie sprechen mit Liza, Ihrem Sprachassistenten. Dürfen wir Ihr Gespräch zur Qualitätsverbesserung verarbeiten?"
            greeting = get_greeting_message(language)
        else:
            greeting = get_greeting_message(language)
        
        # Speak the greeting
        logger.info(f"Using voice: {Config.VOICE_NAME}")
        response.say(greeting, language=language, voice=Config.VOICE_NAME)
        
        # Log greeting conversation
        log_conversation(call.id, 'greeting', bot_response=greeting)
        
        # Get consent prompts
        consent_prompts = get_consent_prompts(language)
        
        # Gather user response for consent
        gather = response.gather(
            input='dtmf',
            timeout=15,
            num_digits=1,
            action='/webhook/consent',
            method='POST'
        )
        
        # If no input, repeat the prompt
        gather.say(consent_prompts['yes'], language=language, voice=Config.VOICE_NAME,
                   voice_engine='neural' if Config.VOICE_NAME.startswith('polly.') else 'standard')
        
        # If no response, say goodbye
        response.say(get_goodbye_message(language), language=language, voice=Config.VOICE_NAME)
        response.hangup()
        
        return Response(str(response), mimetype='text/xml')
        
    except Exception as e:
        logger.error(f"Error handling incoming call: {str(e)}")
        response = VoiceResponse()
        response.say('Sorry, there was an error. Please try again later.', voice=Config.VOICE_NAME)
        response.hangup()
        return Response(str(response), mimetype='text/xml')

@app.route('/webhook/consent', methods=['POST'])
def handle_consent():
    """Handle user consent response"""
    try:
        # Get the DTMF result (keypad input)
        dtmf_result = request.form.get('Digits', '').strip()
        caller_number = request.form.get('From', '')
        call_sid = request.form.get('CallSid', '')
        
        logger.info(f"Consent response from {caller_number}: {dtmf_result}")
        
        # Get call record
        call = Call.query.filter_by(call_sid=call_sid).first()
        if not call:
            logger.error(f"Call record not found for {call_sid}")
            response = VoiceResponse()
            response.say('Sorry, there was an error. Please try again later.', voice=Config.VOICE_NAME)
            response.hangup()
            return Response(str(response), mimetype='text/xml')
        
        # Detect language again
        language = detect_language(caller_number)
        consent_prompts = get_consent_prompts(language)
        
        # Log consent conversation
        log_conversation(call.id, 'consent', user_input=dtmf_result)
        
        response = VoiceResponse()
        
        # Check for positive consent (1 = Yes, 2 = No)
        if dtmf_result == '1':
            # User consented
            logger.info(f"User {caller_number} consented to data processing")
            
            # Use static consent response
            if language == 'de':
                consent_response = "Vielen Dank für Ihre Zustimmung. Bitte teilen Sie mir nun mit, wie ich Ihnen behilflich sein kann."
            else:
                consent_response = "Thank you for your consent. I'm Liza and I'm happy to help you. How can I help you today?"
            response.say(consent_response, voice=Config.VOICE_NAME,
                        voice_engine='neural' if Config.VOICE_NAME.startswith('polly.') else 'standard')
            
            # Log consent response and update status
            log_conversation(call.id, 'consent_response', bot_response=consent_response)
            update_call_status(call.id, CallStatus.HANDLED)
            
            # Ask about order status
            if language == 'de':
                order_prompt = "Bitte geben Sie jetzt Ihre Bestellnummer ein und drücken Sie die Raute-Taste, wenn Sie fertig sind."
            else:
                order_prompt = "If you would like to know the status of your item, please enter your order number using the keypad. Press the hash key # when you are finished."
            
            response.say(order_prompt, voice=Config.VOICE_NAME,
                        voice_engine='neural' if Config.VOICE_NAME.startswith('polly.') else 'standard')
            
            # Gather order number via DTMF (keypad)
            gather = response.gather(
                input='dtmf',
                timeout=30,  # Increased timeout
                finishOnKey='#',  # Finish input when # is pressed
                action='/webhook/order',
                method='POST'
            )
            
            # If no response, say goodbye
            response.say(get_goodbye_message(language), voice=Config.VOICE_NAME)
            response.hangup()
            
        elif dtmf_result == '2':
            # User declined, but continue anyway
            logger.info(f"User {caller_number} declined data processing, but continuing")
            
            # Use static consent response
            if language == 'de':
                consent_response = "Danke für Ihren Anruf. Ich helfe Ihnen gerne weiter. Wie kann ich Ihnen behilflich sein?"
            else:
                consent_response = "Thank you for calling. I'm happy to help you. How can I help you today?"
            response.say(consent_response, voice=Config.VOICE_NAME,
                        voice_engine='neural' if Config.VOICE_NAME.startswith('polly.') else 'standard')
            
            # Log consent response and update status
            log_conversation(call.id, 'consent_declined_but_continued', bot_response=consent_response)
            update_call_status(call.id, CallStatus.HANDLED)
            
            # Ask about order status (same as if they consented)
            if language == 'de':
                order_prompt = "Bitte geben Sie jetzt Ihre Bestellnummer ein und drücken Sie die Raute-Taste, wenn Sie fertig sind."
            else:
                order_prompt = "If you would like to know the status of your item, please enter your order number using the keypad. Press the hash key # when you are finished."
            
            response.say(order_prompt, voice=Config.VOICE_NAME,
                        voice_engine='neural' if Config.VOICE_NAME.startswith('polly.') else 'standard')
            
            # Gather order number via DTMF (keypad)
            gather = response.gather(
                input='dtmf',
                timeout=30,
                finishOnKey='#',
                action='/webhook/order',
                method='POST'
            )
            
            # If no response, say goodbye
            response.say(get_goodbye_message(language), voice=Config.VOICE_NAME)
            response.hangup()
            
        else:
            # Invalid response
            logger.warning(f"Invalid consent response '{dtmf_result}' from {caller_number}")
            
            # Use static consent response
            if language == 'de':
                invalid_response = "Entschuldigung, ich habe Ihre Antwort nicht verstanden. Drücken Sie 1 für Ja oder 2 für Nein."
            else:
                invalid_response = "Sorry, I didn't understand your response. Press 1 for Yes or 2 for No."
            
            response.say(invalid_response, voice=Config.VOICE_NAME,
                        voice_engine='neural' if Config.VOICE_NAME.startswith('polly.') else 'standard')
            
            # Log invalid response
            log_conversation(call.id, 'invalid_consent', bot_response=invalid_response)
            
            # Ask for consent again
            gather = response.gather(
                input='dtmf',
                timeout=15,
                num_digits=1,
                action='/webhook/consent',
                method='POST'
            )
            
            # If no response, say goodbye
            if language == 'de':
                response.say(get_goodbye_message(language), voice=Config.VOICE_NAME)
            else:
                response.say(get_goodbye_message(language), voice=Config.VOICE_NAME)
            response.hangup()
        
        return Response(str(response), mimetype='text/xml')
        
    except Exception as e:
        logger.error(f"Error handling consent: {str(e)}")
        response = VoiceResponse()
        response.say('Sorry, there was an error. Please try again later.', voice=Config.VOICE_NAME)
        response.hangup()
        return Response(str(response), mimetype='text/xml')

@app.route('/webhook/order', methods=['POST'])
def handle_order():
    """Handle order number input"""
    try:
        # Get the DTMF result (keypad input)
        dtmf_result = request.form.get('Digits', '').strip()
        caller_number = request.form.get('From', '')
        call_sid = request.form.get('CallSid', '')
        
        logger.info(f"Order number from {caller_number}: {dtmf_result}")
        
        # Get call record
        call = Call.query.filter_by(call_sid=call_sid).first()
        if not call:
            logger.error(f"Call record not found for {call_sid}")
            response = VoiceResponse()
            response.say('Sorry, there was an error. Please try again later.', voice=Config.VOICE_NAME)
            response.hangup()
            return Response(str(response), mimetype='text/xml')
        
        # Detect language again
        language = detect_language(caller_number)
        
        # Log order input
        log_conversation(call.id, 'order_input', user_input=dtmf_result)
        
        response = VoiceResponse()
        
        if dtmf_result:
            # Validate order number
            is_valid, validation_reason = validate_order_number(dtmf_result, language)
            
            if not is_valid:
                # Invalid order number - ask for clarification
                logger.warning(f"Invalid order number '{dtmf_result}' from {caller_number}: {validation_reason}")
                
                if language == 'de':
                    invalid_response = f"Entschuldigung, ich habe '{dtmf_result}' nicht als gültige Bestellnummer erkannt. Bitte geben Sie Ihre Bestellnummer erneut über die Tastatur ein."
                else:
                    invalid_response = f"Sorry, I didn't recognize '{dtmf_result}' as a valid order number. Please enter your order number again using the keypad."
                
                response.say(invalid_response, voice=Config.VOICE_NAME,
                            voice_engine='neural' if Config.VOICE_NAME.startswith('polly.') else 'standard')
                
                # Log invalid response
                log_conversation(call.id, 'invalid_order_response', bot_response=invalid_response)
                
                # Ask for order number again
                if language == 'de':
                    retry_prompt = "Bitte geben Sie Ihre Bestellnummer erneut über die Tastatur ein. Drücken Sie die Raute-Taste # wenn Sie fertig sind."
                else:
                    retry_prompt = "Please enter your order number again using the keypad. Press the hash key # when you are finished."
                
                gather = response.gather(
                    input='dtmf',
                    timeout=30,
                    finishOnKey='#',
                    action='/webhook/order',
                    method='POST'
                )
                
                # If no response, say goodbye
                if language == 'de':
                    response.say(get_goodbye_message(language), voice=Config.VOICE_NAME)
                else:
                    response.say(get_goodbye_message(language), voice=Config.VOICE_NAME)
                response.hangup()
                
                return Response(str(response), mimetype='text/xml')
            
            # Valid order number - ask for confirmation
            formatted_number = format_order_number_for_speech(dtmf_result)
            if language == 'de':
                confirmation_response = f"Sie haben die folgende Bestellnummer {formatted_number} eingetippt? Bitte bestätigen Sie durch 1 für Ja oder 2 für Nein."
            else:
                confirmation_response = f"You have entered order number {formatted_number}. Is this correct? Press 1 for Yes or 2 for No."
            
            response.say(confirmation_response, voice=Config.VOICE_NAME,
                        voice_engine='neural' if Config.VOICE_NAME.startswith('polly.') else 'standard')
            
            # Log confirmation request
            log_conversation(call.id, 'order_confirmation_request', bot_response=confirmation_response)
            
            # Gather confirmation (1 for Yes, 2 for No)
            gather = response.gather(
                input='dtmf',
                timeout=10,
                num_digits=1,
                action='/webhook/order_confirm',
                method='POST'
            )
            
            # If no response, say goodbye
            if language == 'de':
                response.say(get_goodbye_message(language), voice=Config.VOICE_NAME)
            else:
                response.say(get_goodbye_message(language), voice=Config.VOICE_NAME)
            response.hangup()
            
            return Response(str(response), mimetype='text/xml')
            
            response.say(order_response, voice=Config.VOICE_NAME,
                        voice_engine='neural' if Config.VOICE_NAME.startswith('polly.') else 'standard')
            
            # Log order response
            log_conversation(call.id, 'order_response', bot_response=order_response)
            
            # Save order to database
            order = Order(
                call_id=call.id,
                order_number=dtmf_result,
                status="In Progress",
                notes="Order status checked via voice assistant"
            )
            db.session.add(order)
            db.session.commit()
            
            # Simulate processing time
            response.pause(length=2)
            
            response.say(status_response, voice=Config.VOICE_NAME,
                        voice_engine='neural' if Config.VOICE_NAME.startswith('polly.') else 'standard')
            
            # Log status response
            log_conversation(call.id, 'status_response', bot_response=status_response)
            
            # Ask if they need more help
            if language == 'de':
                help_prompt = "Können Sie mir noch bei etwas anderem helfen?"
            else:
                help_prompt = "Can I help you with anything else?"
            
            gather = response.gather(
                input='speech',
                timeout=5,
                speech_timeout='auto',
                language=language,
                action='/webhook/help',
                method='POST'
            )
            
            # If no response, say goodbye
            if language == 'de':
                response.say(get_goodbye_message(language), voice=Config.VOICE_NAME)
            else:
                response.say(get_goodbye_message(language), voice=Config.VOICE_NAME)
            response.hangup()
            
        else:
            # No order number provided - transfer to manager
            logger.info(f"No order number provided by {caller_number}, transferring to manager")
            
            if language == 'de':
                transfer_msg = "Ich konnte keine Bestellnummer verstehen. Ich verbinde Sie jetzt mit einem unserer Mitarbeiter. Einen Moment bitte."
            else:
                transfer_msg = "I didn't understand an order number. I'm now connecting you with one of our staff. Please hold."
            
            response.say(transfer_msg, voice=Config.VOICE_NAME,
                        voice_engine='neural' if Config.VOICE_NAME.startswith('polly.') else 'standard')
            
            # Log and transfer to manager
            log_conversation(call.id, 'no_order_transfer_to_manager', bot_response=transfer_msg)
            update_call_status(call.id, CallStatus.HANDLED)
            
            # Redirect to manager's phone number
            manager_phone = "+4973929378421"  # 07392 - 93 78 421
            response.dial(number=manager_phone, caller_id=caller_number)
        
        return Response(str(response), mimetype='text/xml')
        
    except Exception as e:
        logger.error(f"Error handling order: {str(e)}")
        response = VoiceResponse()
        response.say('Sorry, there was an error. Please try again later.', voice=Config.VOICE_NAME)
        response.hangup()
        return Response(str(response), mimetype='text/xml')

@app.route('/webhook/order_confirm', methods=['POST'])
def handle_order_confirm():
    """Handle order number confirmation"""
    try:
        # Get the confirmation result (1 for Yes, 2 for No)
        confirmation = request.form.get('Digits', '').strip()
        caller_number = request.form.get('From', '')
        call_sid = request.form.get('CallSid', '')
        
        logger.info(f"Order confirmation from {caller_number}: {confirmation}")
        
        # Get call record
        call = Call.query.filter_by(call_sid=call_sid).first()
        if not call:
            logger.error(f"Call record not found for {call_sid}")
            response = VoiceResponse()
            response.say('Sorry, there was an error. Please try again later.', voice=Config.VOICE_NAME)
            response.hangup()
            return Response(str(response), mimetype='text/xml')
        
        # Detect language
        language = detect_language(caller_number)
        
        # Get the order number from the last conversation
        last_conversation = Conversation.query.filter_by(
            call_id=call.id, 
            step='order_input'
        ).order_by(Conversation.timestamp.desc()).first()
        
        if not last_conversation:
            logger.error(f"No order input found for call {call_sid}")
            response = VoiceResponse()
            response.say('Sorry, there was an error. Please try again later.', voice=Config.VOICE_NAME)
            response.hangup()
            return Response(str(response), mimetype='text/xml')
        
        order_number = last_conversation.user_input
        response = VoiceResponse()
        
        if confirmation == '1':  # Yes - confirmed
            logger.info(f"Order {order_number} confirmed by {caller_number}")
            
            # Log confirmation
            log_conversation(call.id, 'order_confirmed', user_input='1')
            
            # Get real order data from AfterBuy
            order_data = get_order_from_afterbuy(order_number)
            
            # Process confirmed order
            formatted_number = format_order_number_for_speech(order_number)
            if language == 'de':
                order_response = f"Vielen Dank! Ich habe Ihre Bestellnummer {formatted_number} bestätigt. Ich prüfe den Status für Sie. Bitte warten Sie einen Moment."
            else:
                order_response = f"Thank you! I have confirmed your order number {formatted_number}. I am checking the status for you. Please wait a moment."
            
            response.say(order_response, voice=Config.VOICE_NAME,
                        voice_engine='neural' if Config.VOICE_NAME.startswith('polly.') else 'standard')
            
            # Log order response
            log_conversation(call.id, 'order_response', bot_response=order_response)
            
            # Get real status from AfterBuy
            if order_data:
                status_response = format_order_status_for_speech(order_data, language)
                
                # Save order to database with real data
                order = Order(
                    call_id=call.id,
                    order_number=order_number,
                    status="Found in AfterBuy",
                    notes=f"Order found: {order_data.get('invoice_number', 'N/A')} - {order_data.get('buyer', {}).get('first_name', 'Unknown')} {order_data.get('buyer', {}).get('last_name', '')}"
                )
            else:
                # Order not found in AfterBuy
                if language == 'de':
                    status_response = f"Entschuldigung, ich konnte keinen Auftrag mit der Nummer {formatted_number} in unserem System finden. Bitte überprüfen Sie die Nummer oder kontaktieren Sie unseren Kundenservice."
                else:
                    status_response = f"Sorry, I couldn't find an order with number {formatted_number} in our system. Please check the number or contact our customer service."
                
                # Save order to database as not found
                order = Order(
                    call_id=call.id,
                    order_number=order_number,
                    status="Not Found",
                    notes="Order not found in AfterBuy system"
                )
            
            db.session.add(order)
            db.session.commit()
            
            # Simulate processing time
            response.pause(length=2)
            
            response.say(status_response, voice=Config.VOICE_NAME,
                        voice_engine='neural' if Config.VOICE_NAME.startswith('polly.') else 'standard')
            
            # Log status response
            log_conversation(call.id, 'status_response', bot_response=status_response)
            
            # Ask if they need more help (voice message option)
            if language == 'de':
                help_prompt = "Wenn Sie noch Fragen haben, drücken Sie 1 um eine Nachricht zu hinterlassen, oder drücken Sie 2 um mit einem Mitarbeiter verbunden zu werden."
            else:
                help_prompt = "If you have any questions, press 1 to leave a message, or press 2 to speak to a staff member."
            
            response.say(help_prompt, voice=Config.VOICE_NAME,
                        voice_engine='neural' if Config.VOICE_NAME.startswith('polly.') else 'standard')
            
            gather = response.gather(
                input='dtmf',
                timeout=10,
                num_digits=1,
                action='/webhook/voice_message',
                method='POST'
            )
            
            # If no response, say goodbye
            if language == 'de':
                response.say(get_goodbye_message(language), voice=Config.VOICE_NAME)
            else:
                response.say(get_goodbye_message(language), voice=Config.VOICE_NAME)
            response.hangup()
            
        elif confirmation == '2':  # No - not confirmed
            logger.info(f"Order {order_number} not confirmed by {caller_number}")
            
            # Log rejection
            log_conversation(call.id, 'order_rejected', user_input='2')
            
            # Ask for order number again
            if language == 'de':
                retry_response = "Verstanden. Bitte geben Sie Ihre Bestellnummer erneut über die Tastatur ein. Drücken Sie die Raute-Taste # wenn Sie fertig sind."
            else:
                retry_response = "Understood. Please enter your order number again using the keypad. Press the hash key # when you are finished."
            
            response.say(retry_response, voice=Config.VOICE_NAME,
                        voice_engine='neural' if Config.VOICE_NAME.startswith('polly.') else 'standard')
            
            # Log retry response
            log_conversation(call.id, 'order_retry_request', bot_response=retry_response)
            
            # Ask for order number again
            gather = response.gather(
                input='dtmf',
                timeout=30,
                finishOnKey='#',
                action='/webhook/order',
                method='POST'
            )
            
            # If no response, say goodbye
            if language == 'de':
                response.say(get_goodbye_message(language), voice=Config.VOICE_NAME)
            else:
                response.say(get_goodbye_message(language), voice=Config.VOICE_NAME)
            response.hangup()
            
        else:  # Invalid confirmation
            logger.warning(f"Invalid confirmation '{confirmation}' from {caller_number}")
            
            # Log invalid confirmation
            log_conversation(call.id, 'invalid_confirmation', user_input=confirmation)
            
            # Ask for confirmation again
            formatted_number = format_order_number_for_speech(order_number)
            if language == 'de':
                invalid_response = f"Entschuldigung, ich habe Ihre Antwort nicht verstanden. Sie haben die Bestellnummer {formatted_number} eingegeben. Ist das korrekt? Drücken Sie 1 für Ja oder 2 für Nein."
            else:
                invalid_response = f"Sorry, I didn't understand your response. You have entered order number {formatted_number}. Is this correct? Press 1 for Yes or 2 for No."
            
            response.say(invalid_response, voice=Config.VOICE_NAME,
                        voice_engine='neural' if Config.VOICE_NAME.startswith('polly.') else 'standard')
            
            # Log invalid response
            log_conversation(call.id, 'invalid_confirmation_response', bot_response=invalid_response)
            
            # Gather confirmation again
            gather = response.gather(
                input='dtmf',
                timeout=10,
                num_digits=1,
                action='/webhook/order_confirm',
                method='POST'
            )
            
            # If no response, say goodbye
            if language == 'de':
                response.say(get_goodbye_message(language), voice=Config.VOICE_NAME)
            else:
                response.say(get_goodbye_message(language), voice=Config.VOICE_NAME)
            response.hangup()
        
        return Response(str(response), mimetype='text/xml')
        
    except Exception as e:
        logger.error(f"Error handling order confirmation: {str(e)}")
        response = VoiceResponse()
        response.say('Sorry, there was an error. Please try again later.', voice=Config.VOICE_NAME)
        response.hangup()
        return Response(str(response), mimetype='text/xml')

@app.route('/webhook/help', methods=['POST'])
def handle_help():
    """Handle additional help requests"""
    try:
        speech_result = request.form.get('SpeechResult', '').lower().strip()
        caller_number = request.form.get('From', '')
        language = detect_language(caller_number)
        
        logger.info(f"Help request from {caller_number}: {speech_result}")
        
        response = VoiceResponse()
        
        # Check if they need more help
        if any(word in speech_result for word in ['ja', 'yes', 'jawohl', 'sure', 'ok']):
            if language == 'de':
                help_response = "Gerne! Womit kann ich Ihnen noch helfen? Sie können nach dem Status einer anderen Bestellung fragen oder andere Fragen stellen."
            else:
                help_response = "Of course! How else can I help you? You can ask about the status of another order or ask other questions."
            
            response.say(help_response, voice=Config.VOICE_NAME,
                        voice_engine='neural' if Config.VOICE_NAME.startswith('polly.') else 'standard')
            
            # Ask for order number again
            if language == 'de':
                order_prompt = "Wenn Sie den Status einer anderen Bestellung erfahren möchten, diktieren Sie bitte die Bestellnummer."
            else:
                order_prompt = "If you would like to know the status of another order, please dictate the order number."
            
            gather = response.gather(
                input='speech',
                timeout=10,
                speech_timeout='auto',
                language=language,
                action='/webhook/order',
                method='POST'
            )
            
            # If no response, say goodbye
            if language == 'de':
                response.say(get_goodbye_message(language), voice=Config.VOICE_NAME)
            else:
                response.say(get_goodbye_message(language), voice=Config.VOICE_NAME)
            response.hangup()
            
        else:
            # They don't need more help
            if language == 'de':
                goodbye_response = get_goodbye_message(language)
            else:
                goodbye_response = get_goodbye_message(language)
            
            response.say(goodbye_response, voice=Config.VOICE_NAME,
                        voice_engine='neural' if Config.VOICE_NAME.startswith('polly.') else 'standard')
            response.hangup()
        
        return Response(str(response), mimetype='text/xml')
        
    except Exception as e:
        logger.error(f"Error handling help: {str(e)}")
        response = VoiceResponse()
        response.say(get_goodbye_message(language), voice=Config.VOICE_NAME)
        response.hangup()
        return Response(str(response), mimetype='text/xml')

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return {'status': 'healthy', 'message': 'Voice assistant is running'}

@app.route('/', methods=['GET'])
def dashboard():
    """Dashboard home page"""
    # Get statistics
    total_calls = Call.query.count()
    completed_calls = Call.query.filter_by(status=CallStatus.COMPLETED).count()
    processing_calls = Call.query.filter_by(status=CallStatus.PROCESSING).count()
    problem_calls = Call.query.filter_by(status=CallStatus.PROBLEM).count()
    handled_calls = Call.query.filter_by(status=CallStatus.HANDLED).count()
    
    stats = {
        'total_calls': total_calls,
        'completed_calls': completed_calls,
        'processing_calls': processing_calls,
        'problem_calls': problem_calls,
        'handled_calls': handled_calls
    }
    
    # Get recent calls
    recent_calls = Call.query.order_by(desc(Call.created_at)).limit(10).all()
    
    return render_template('dashboard.html', stats=stats, recent_calls=recent_calls)

@app.route('/calls', methods=['GET'])
def calls():
    """Calls list page with filtering"""
    page = request.args.get('page', 1, type=int)
    status_filter = request.args.get('status')
    language_filter = request.args.get('language')
    phone_filter = request.args.get('phone')
    
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
    
    return render_template('calls.html', calls=calls)

@app.route('/calls/<int:call_id>', methods=['GET'])
def call_detail(call_id):
    """Call detail page"""
    call = Call.query.get_or_404(call_id)
    conversations = Conversation.query.filter_by(call_id=call_id).order_by(Conversation.timestamp).all()
    orders = Order.query.filter_by(call_id=call_id).all()
    
    return render_template('call_detail.html', 
                         call=call, 
                         conversations=conversations, 
                         orders=orders)

@app.route('/api/calls/<int:call_id>/status', methods=['POST'])
def update_call_status_api(call_id):
    """Update call status via API"""
    try:
        data = request.get_json()
        new_status = data.get('status')
        
        if not new_status or new_status not in [status.name for status in CallStatus]:
            return {'error': 'Invalid status'}, 400
        
        call = Call.query.get_or_404(call_id)
        call.status = CallStatus[new_status]
        db.session.commit()
        
        logger.info(f"Call {call_id} status updated to {new_status}")
        return {'message': 'Status updated successfully', 'status': new_status}
        
    except Exception as e:
        logger.error(f"Error updating call status: {e}")
        return {'error': 'Failed to update status'}, 500

@app.route('/api/orders/<int:order_id>/status', methods=['POST'])
def update_order_status_api(order_id):
    """Update order status via API"""
    try:
        data = request.get_json()
        new_status = data.get('status')
        notes = data.get('notes', '')
        
        if not new_status:
            return {'error': 'Status is required'}, 400
        
        order = Order.query.get_or_404(order_id)
        order.status = new_status
        if notes:
            order.notes = notes
        # Update updated_at timestamp
        from datetime import datetime
        order.updated_at = datetime.utcnow()
        db.session.commit()
        
        logger.info(f"Order {order_id} status updated to {new_status}")
        return {'message': 'Order status updated successfully', 'status': new_status}
        
    except Exception as e:
        logger.error(f"Error updating order status: {e}")
        return {'error': 'Failed to update order status'}, 500

@app.route('/orders', methods=['GET'])
def orders():
    """Orders list page with filtering"""
    page = request.args.get('page', 1, type=int)
    status_filter = request.args.get('status')
    phone_filter = request.args.get('phone')
    order_number_filter = request.args.get('order_number')
    
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
    
    return render_template('orders.html', orders=orders)

@app.route('/orders/<int:order_id>', methods=['GET'])
def order_detail(order_id):
    """Order detail page"""
    order = Order.query.get_or_404(order_id)
    return render_template('order_detail.html', order=order)

@app.route('/webhook/voice_message', methods=['POST'])
def handle_voice_message():
    """Handle voice message choice (1 = leave message, 2 = end call)"""
    try:
        digits = request.form.get('Digits', '').strip()
        caller_number = request.form.get('From', '')
        call_sid = request.form.get('CallSid', '')
        
        logger.info(f"Voice message choice from {caller_number}: {digits}")
        
        # Get call record
        call = Call.query.filter_by(call_sid=call_sid).first()
        if not call:
            logger.error(f"Call record not found for {call_sid}")
            response = VoiceResponse()
            response.say('Sorry, there was an error. Please try again later.', voice=Config.VOICE_NAME)
            response.hangup()
            return Response(str(response), mimetype='text/xml')
        
        language = detect_language(caller_number)
        response = VoiceResponse()
        
        if digits == '1':  # User wants to leave a voice message
            logger.info(f"User {caller_number} wants to leave a voice message")
            
            if language == 'de':
                message_prompt = "Bitte hinterlassen Sie nach dem Signalton eine Nachricht. Sie erhalten innerhalb von 24 Stunden eine Antwort per E-Mail."
            else:
                message_prompt = "Please leave a message after the tone. You will receive a reply by email within 24 hours."
            
            response.say(message_prompt, voice=Config.VOICE_NAME,
                        voice_engine='neural' if Config.VOICE_NAME.startswith('polly.') else 'standard')
            
            # Record the message with transcription
            response.record(
                maxLength=60,  # 60 seconds max
                action='/webhook/recorded',
                method='POST',
                recordingStatusCallback='/webhook/recording_status',
                transcribe=True,  # Enable transcription
                transcribeCallback='/webhook/transcription'  # Callback for transcription
            )
            
            # Log action
            log_conversation(call.id, 'voice_message_request', bot_response=message_prompt)
            
        elif digits == '2':  # User wants to speak to manager
            logger.info(f"User {caller_number} wants to speak to manager")
            
            if language == 'de':
                transfer_msg = "Ich verbinde Sie jetzt mit einem unserer Mitarbeiter. Einen Moment bitte."
            else:
                transfer_msg = "I'm now connecting you with one of our staff. Please hold."
            
            response.say(transfer_msg, voice=Config.VOICE_NAME,
                        voice_engine='neural' if Config.VOICE_NAME.startswith('polly.') else 'standard')
            
            # Redirect to manager's phone number
            manager_phone = "+4973929378421"  # 07392 - 93 78 421
            response.dial(number=manager_phone, caller_id=caller_number)
            
            # Log action
            log_conversation(call.id, 'transfer_to_manager', bot_response=transfer_msg)
            
        else:  # Invalid choice
            logger.warning(f"Invalid voice message choice '{digits}' from {caller_number}")
            
            if language == 'de':
                error_msg = "Entschuldigung, ich habe Ihre Antwort nicht verstanden. Wenn Sie noch Fragen haben, drücken Sie 1. Um mit einem Mitarbeiter verbunden zu werden, drücken Sie 2."
            else:
                error_msg = "Sorry, I didn't understand your response. If you have questions, press 1. To speak to a staff member, press 2."
            
            response.say(error_msg, voice=Config.VOICE_NAME,
                        voice_engine='neural' if Config.VOICE_NAME.startswith('polly.') else 'standard')
            
            gather = response.gather(
                input='dtmf',
                timeout=10,
                num_digits=1,
                action='/webhook/voice_message',
                method='POST'
            )
            
            # Fallback
            if language == 'de':
                response.say(get_goodbye_message(language), voice=Config.VOICE_NAME)
            else:
                response.say(get_goodbye_message(language), voice=Config.VOICE_NAME)
            response.hangup()
        
        return Response(str(response), mimetype='text/xml')
        
    except Exception as e:
        logger.error(f"Error handling voice message: {str(e)}")
        response = VoiceResponse()
        response.say('Sorry, there was an error. Please try again later.', voice=Config.VOICE_NAME)
        response.hangup()
        return Response(str(response), mimetype='text/xml')

@app.route('/webhook/recorded', methods=['POST'])
def handle_recorded():
    """Handle recorded voice message"""
    try:
        recording_url = request.form.get('RecordingUrl', '')
        recording_transcription = request.form.get('RecordingTranscription', '') or request.form.get('TranscriptionText', '')
        caller_number = request.form.get('From', '')
        call_sid = request.form.get('CallSid', '')
        
        logger.info(f"Voice message recorded from {caller_number}")
        logger.info(f"Recording URL: {recording_url}")
        logger.info(f"Recording Transcription: {recording_transcription}")
        
        # Get call record
        call = Call.query.filter_by(call_sid=call_sid).first()
        if call:
            # Save recording transcription text to conversation
            language = detect_language(caller_number)
            
            if language == 'de':
                thank_you = "Vielen Dank für Ihre Nachricht. Wir melden uns innerhalb von 24 Stunden bei Ihnen. Auf Wiedersehen!"
            else:
                thank_you = "Thank you for your message. We will contact you within 24 hours. Goodbye!"
            
            # Save the transcription text, not just URL
            transcription_text = recording_transcription if recording_transcription else f"Voice message recorded (URL: {recording_url})"
            
            log_conversation(call.id, 'voice_message_recorded', 
                           user_input=transcription_text,
                           bot_response=thank_you)
            
            # Also save to order notes
            orders = Order.query.filter_by(call_id=call.id).order_by(Order.created_at.desc()).all()
            if orders:
                order = orders[0]
                if order.notes:
                    order.notes += f"\n\nVoice message: {transcription_text}"
                else:
                    order.notes = f"Voice message: {transcription_text}"
                db.session.commit()
            
            update_call_status(call.id, CallStatus.COMPLETED)
            
            response = VoiceResponse()
            response.say(thank_you, voice=Config.VOICE_NAME,
                        voice_engine='neural' if Config.VOICE_NAME.startswith('polly.') else 'standard')
            response.hangup()
        else:
            response = VoiceResponse()
            response.say(get_goodbye_message(language), voice=Config.VOICE_NAME)
            response.hangup()
        
        return Response(str(response), mimetype='text/xml')
        
    except Exception as e:
        logger.error(f"Error handling recorded message: {str(e)}")
        response = VoiceResponse()
        response.say('Thank you for your message. Goodbye!', voice=Config.VOICE_NAME)
        response.hangup()
        return Response(str(response), mimetype='text/xml')

@app.route('/webhook/transcription', methods=['POST'])
def handle_transcription():
    """Handle transcription callback from Twilio"""
    try:
        transcription_text = request.form.get('TranscriptionText', '')
        transcription_status = request.form.get('TranscriptionStatus', '')
        call_sid = request.form.get('CallSid', '')
        recording_sid = request.form.get('RecordingSid', '')
        
        logger.info(f"Transcription received: Status={transcription_status}, Text='{transcription_text[:100]}...'")
        
        # Get call record
        call = Call.query.filter_by(call_sid=call_sid).first()
        if call and transcription_text:
            # Update the conversation with transcription text
            conversations = Conversation.query.filter_by(
                call_id=call.id, 
                step='voice_message_recorded'
            ).order_by(Conversation.timestamp.desc()).all()
            
            if conversations:
                conversation = conversations[0]
                conversation.user_input = transcription_text
                db.session.commit()
                logger.info(f"Updated conversation {conversation.id} with transcription text")
            
            # Also update order notes
            orders = Order.query.filter_by(call_id=call.id).order_by(Order.created_at.desc()).all()
            if orders:
                order = orders[0]
                if order.notes:
                    order.notes = order.notes.replace(
                        "Voice message: Voice message recorded (URL:",
                        f"Voice message transcription: {transcription_text}"
                    )
                else:
                    order.notes = f"Voice message transcription: {transcription_text}"
                db.session.commit()
        
        return Response(status=200)
        
    except Exception as e:
        logger.error(f"Error handling transcription: {str(e)}")
        return Response(status=500)

@app.route('/webhook/recording_status', methods=['POST'])
def handle_recording_status():
    """Handle recording status callback"""
    try:
        recording_url = request.form.get('RecordingUrl', '')
        recording_sid = request.form.get('RecordingSid', '')
        recording_status = request.form.get('RecordingStatus', '')
        call_sid = request.form.get('CallSid', '')
        
        logger.info(f"Recording status: {recording_status}, URL: {recording_url}")
        
        # Get call record and save recording info
        call = Call.query.filter_by(call_sid=call_sid).first()
        if call:
            # Update order notes with recording info
            orders = Order.query.filter_by(call_id=call.id).order_by(Order.created_at.desc()).all()
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

@app.route('/api/health', methods=['GET'])
def api_health():
    """API health check"""
    return {
        'message': 'Voice Assistant with Database',
        'endpoints': {
            'webhook': '/webhook/voice',
            'health': '/api/health',
            'dashboard': '/'
        }
    }

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=Config.FLASK_DEBUG, host='0.0.0.0', port=5001)
