import config
from flask import Flask, request, Response, render_template, url_for
from twilio.twiml.voice_response import VoiceResponse
import logging
from config import Config
from models import db, Call, Conversation, Order, CallStatus
from sqlalchemy import desc
# ChatGPT removed - using static text

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config.from_object(Config)

# Initialize database
db.init_app(app)


# Language detection based on caller's country or phone number
def detect_language(caller_number):
    """
    Detect language based on caller's phone number
    Default to German, English for US/UK numbers
    """
    # Remove + and spaces from phone number
    clean_number = caller_number.replace('+', '').replace(' ', '')
    
    # Simple country code detection
    if clean_number.startswith('1'):  # US/Canada
        return 'en'
    elif clean_number.startswith('44'):  # UK
        return 'en'
    else:  # Default to German for all other numbers
        return 'de'

def get_greeting_message(language):
    """Get the appropriate greeting message based on language"""
    messages = {
        'de': f"""Guten Tag!
Sie sprechen mit einem automatischen Sprachassistenten von {Config.COMPANY_NAME}.
Dieses Gespräch kann zur Verbesserung unseres Services verarbeitet werden.
Weitere Informationen zum Datenschutz finden Sie unter {Config.WEBSITE_URL} oder erhalten Sie auf Wunsch von einem Mitarbeiter.
Stimmen Sie der Verarbeitung Ihrer Daten zu?""",
        
        'en': f"""Hello!
You are speaking with an automated voice assistant from {Config.COMPANY_NAME}.
This conversation may be processed to improve our services.
You can find more information about data protection at {Config.WEBSITE_URL} or request it from one of our staff.
Do you agree to the processing of your data?"""
    }
    
    return messages.get(language, messages['de'])  # Default to German

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

def format_order_number_for_speech(order_number):
    """Format order number for speech - pronounce each digit separately"""
    if not order_number:
        return order_number
    
    # Separate each digit with spaces - no SSML tags
    digits = ' '.join(list(str(order_number)))
    return digits

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
            greeting = f"Guten Tag! Sie sprechen mit Liza, Ihrem Sprachassistenten von {Config.COMPANY_NAME}. Dieses Gespräch kann zur Verbesserung unseres Services verarbeitet werden. Stimmen Sie der Verarbeitung Ihrer Daten zu?"
        else:
            greeting = "Hello! You are speaking with Liza, your voice assistant from JVMOEBEL. This conversation may be processed to improve our services. Do you agree to the processing of your data?"
        
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
        response.say('Thank you for calling. Goodbye.', language=language, voice=Config.VOICE_NAME)
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
                consent_response = "Vielen Dank für Ihre Zustimmung. Ich bin Liza und helfe Ihnen gerne. Wie kann ich Ihnen heute helfen?"
            else:
                consent_response = "Thank you for your consent. I'm Liza and I'm happy to help you. How can I help you today?"
            response.say(consent_response, voice=Config.VOICE_NAME,
                        voice_engine='neural' if Config.VOICE_NAME.startswith('polly.') else 'standard')
            
            # Log consent response and update status
            log_conversation(call.id, 'consent_response', bot_response=consent_response)
            update_call_status(call.id, CallStatus.HANDLED)
            
            # Ask about order status
            if language == 'de':
                order_prompt = "Wenn Sie den Status Ihres Artikels erfahren möchten, geben Sie bitte Ihre Bestellnummer über die Tastatur ein. Drücken Sie die Raute-Taste # wenn Sie fertig sind."
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
            response.say('Thank you for calling. Goodbye.', voice=Config.VOICE_NAME)
            response.hangup()
            
        elif dtmf_result == '2':
            # User declined
            logger.info(f"User {caller_number} declined data processing")
            
            # Use static consent response
            if language == 'de':
                consent_response = "Vielen Dank für Ihren Anruf. Ohne Ihre Zustimmung zur Datenverarbeitung können wir leider nicht weiterhelfen. Vielen Dank und einen schönen Tag noch."
            else:
                consent_response = "Thank you for calling. Without your consent for data processing, we cannot help you further. Thank you and have a nice day."
            response.say(consent_response, voice=Config.VOICE_NAME,
                        voice_engine='neural' if Config.VOICE_NAME.startswith('polly.') else 'standard')
            
            # Log consent response and update status
            log_conversation(call.id, 'consent_response', bot_response=consent_response)
            update_call_status(call.id, CallStatus.COMPLETED)
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
                response.say('Vielen Dank für Ihren Anruf. Auf Wiedersehen!', voice=Config.VOICE_NAME)
            else:
                response.say('Thank you for calling. Goodbye!', voice=Config.VOICE_NAME)
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
                    response.say('Vielen Dank für Ihren Anruf. Auf Wiedersehen!', voice=Config.VOICE_NAME)
                else:
                    response.say('Thank you for calling. Goodbye!', voice=Config.VOICE_NAME)
                response.hangup()
                
                return Response(str(response), mimetype='text/xml')
            
            # Valid order number - ask for confirmation
            formatted_number = format_order_number_for_speech(dtmf_result)
            if language == 'de':
                confirmation_response = f"Sie haben die Bestellnummer {formatted_number} eingegeben. Ist das korrekt? Drücken Sie 1 für Ja oder 2 für Nein."
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
                response.say('Vielen Dank für Ihren Anruf. Auf Wiedersehen!', voice=Config.VOICE_NAME)
            else:
                response.say('Thank you for calling. Goodbye!', voice=Config.VOICE_NAME)
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
                response.say('Vielen Dank für Ihren Anruf. Auf Wiedersehen!', voice=Config.VOICE_NAME)
            else:
                response.say('Thank you for calling. Goodbye!', voice=Config.VOICE_NAME)
            response.hangup()
            
        else:
            # No order number provided
            if language == 'de':
                no_order_response = "Entschuldigung, ich habe keine Bestellnummer verstanden. Bitte versuchen Sie es erneut oder rufen Sie später an."
            else:
                no_order_response = "Sorry, I didn't understand an order number. Please try again or call back later."
            
            response.say(no_order_response, voice=Config.VOICE_NAME,
                        voice_engine='neural' if Config.VOICE_NAME.startswith('polly.') else 'standard')
            
            # Log no order response
            log_conversation(call.id, 'no_order_response', bot_response=no_order_response)
            update_call_status(call.id, CallStatus.COMPLETED)
            response.hangup()
        
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
            
            # Process confirmed order
            formatted_number = format_order_number_for_speech(order_number)
            if language == 'de':
                order_response = f"Vielen Dank! Ich habe Ihre Bestellnummer {formatted_number} bestätigt. Ich prüfe den Status für Sie. Bitte warten Sie einen Moment."
                status_response = f"Der Status Ihrer Bestellung {formatted_number} ist: In Bearbeitung. Sie erhalten eine E-Mail mit weiteren Details. Gibt es noch etwas, womit ich Ihnen helfen kann?"
            else:
                order_response = f"Thank you! I have confirmed your order number {formatted_number}. I am checking the status for you. Please wait a moment."
                status_response = f"The status of your order {formatted_number} is: In Progress. You will receive an email with further details. Is there anything else I can help you with?"
            
            response.say(order_response, voice=Config.VOICE_NAME,
                        voice_engine='neural' if Config.VOICE_NAME.startswith('polly.') else 'standard')
            
            # Log order response
            log_conversation(call.id, 'order_response', bot_response=order_response)
            
            # Save order to database
            order = Order(
                call_id=call.id,
                order_number=order_number,
                status="In Progress",
                notes="Order status checked via voice assistant - confirmed by customer"
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
                response.say('Vielen Dank für Ihren Anruf. Auf Wiedersehen!', voice=Config.VOICE_NAME)
            else:
                response.say('Thank you for calling. Goodbye!', voice=Config.VOICE_NAME)
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
                response.say('Vielen Dank für Ihren Anruf. Auf Wiedersehen!', voice=Config.VOICE_NAME)
            else:
                response.say('Thank you for calling. Goodbye!', voice=Config.VOICE_NAME)
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
                response.say('Vielen Dank für Ihren Anruf. Auf Wiedersehen!', voice=Config.VOICE_NAME)
            else:
                response.say('Thank you for calling. Goodbye!', voice=Config.VOICE_NAME)
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
                response.say('Vielen Dank für Ihren Anruf. Auf Wiedersehen!', voice=Config.VOICE_NAME)
            else:
                response.say('Thank you for calling. Goodbye!', voice=Config.VOICE_NAME)
            response.hangup()
            
        else:
            # They don't need more help
            if language == 'de':
                goodbye_response = "Vielen Dank für Ihren Anruf. Auf Wiedersehen!"
            else:
                goodbye_response = "Thank you for calling. Goodbye!"
            
            response.say(goodbye_response, voice=Config.VOICE_NAME,
                        voice_engine='neural' if Config.VOICE_NAME.startswith('polly.') else 'standard')
            response.hangup()
        
        return Response(str(response), mimetype='text/xml')
        
    except Exception as e:
        logger.error(f"Error handling help: {str(e)}")
        response = VoiceResponse()
        response.say('Thank you for calling. Goodbye!', voice=Config.VOICE_NAME)
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
