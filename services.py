from datetime import datetime, date
import smtplib
import logging
from html import escape
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from config import Config

logger = logging.getLogger(__name__)


def detect_language(caller_number: str) -> str:
    """
    Detect language based on caller's phone number
    Default to German, English for US/UK numbers
    """

    clean_number = caller_number.replace("+", "").replace(" ", "")

    if clean_number.startswith("1"):  # US/Canada
        return "en"
    elif clean_number.startswith("44"):  # UK
        return "en"
    else:
        return "de"


def get_greeting_message(language: str) -> str:
    """
    Get the appropriate greeting message based on language
    """

    messages = {
        "de": "Hallo, mein Name ist Lisa. ich bin Ihr automatischer Servicemitarbeiter. Zur Qualitätssicherung können Gespräche aufgezeichnet werden.",
        "en": "Hello, you're speaking with Liza, your voice assistant. May we process your call to improve our service quality?",
    }
    return messages.get(language, messages["de"])


def format_order_number_for_speech(order_number) -> str:
    """
    Format the order number for speech - pronounced as digits
    Example: 1234567890 -> "one two three four five six seven eight nine zero"
    """
    digits = " ".join(list(str(order_number)))
    return digits


def get_goodbye_message(language="de") -> str:
    """Get consistent goodbye message based on language"""
    if language == "de":
        return "Wir bedanken uns für Ihren Anruf und stehen bei weiteren Fragen zur Verfügung!"
    else:
        return "Thank you for calling. We are available for any further questions!"


def get_order_availability_prompt(language: str) -> str:
    """Get prompt asking if user has order number"""
    if language == "de":
        return "Haben Sie eine Bestellnummer? Drücken Sie die 1 für Ja, die 2 für Nein."
    else:
        return "Do you have an order number? Press 1 for Yes, 2 for No."


def get_order_input_prompt(language: str) -> str:
    """Get clear instructions for order number input"""
    if language == "de":
        return "Bitte geben Sie Ihre Bestellnummer über die Tastatur ein. Drücken Sie die # wenn Sie fertig sind."
    else:
        return "Please enter your order number using the keypad. Press the hash key # when you are finished. You have 30 seconds."


def get_no_order_transfer_message(language: str) -> str:
    """Get message when transferring due to no order number"""
    if language == "de":
        return "Verstanden. Ich verbinde Sie jetzt mit einem unserer Mitarbeiter, der Ihnen bei Ihrer Anfrage helfen kann. Einen Moment bitte."
    else:
        return "Understood. I'm now connecting you with one of our staff members who can help you with your inquiry. Please hold."


def check_delivery_overdue(order_data: dict) -> bool:
    """
    Check if the promised delivery date has passed
    Returns True if delivery is overdue
    """
    if not order_data or "promised_delivery_date" not in order_data:
        return False

    promised_date = order_data["promised_delivery_date"]
    if isinstance(promised_date, str):
        try:
            promised_date = datetime.strptime(promised_date, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            # Invalid date format, cannot determine if overdue
            return False

    if not isinstance(promised_date, date):
        return False

    return promised_date < date.today()


def get_overdue_delivery_message(language: str) -> str:
    """Get message for overdue delivery cases"""
    if language == "de":
        return "Ihre Lieferung wird in Kürze erwartet. Ich verbinde Sie nun mit einem Mitarbeiter für weitere Informationen."
    else:
        return "I'm sorry, but your delivery has not arrived yet. I'm now connecting you with one of our staff members who can help you with this issue. Please hold."


def get_delivery_status_message(language: str, order_data: dict) -> str:
    """
    Get appropriate delivery status message based on whether delivery is overdue
    """
    if check_delivery_overdue(order_data):
        return get_overdue_delivery_message(language)
    else:
        # Return normal delivery status message
        if language == "de":
            return f"Ihr Auftrag {format_order_number_for_speech(order_data.get('order_id', ''))}: Ihre Ware befindet sich derzeit in der Produktion und hat eine voraussichtliche Lieferzeit von {order_data.get('production_min_weeks', '')} bis {order_data.get('production_max_weeks', '')} Wochen."
        else:
            return f"Your order {format_order_number_for_speech(order_data.get('order_id', ''))}: Your goods are currently in production and have an expected delivery time of {order_data.get('production_min_weeks', '')} to {order_data.get('production_max_weeks', '')} weeks."


def send_voice_message_email(
    caller_number: str,
    recording_url: str,
    transcription_text: str,
    duration_seconds: int,
    language: str = "de",
    order_number: str = None,
) -> bool:
    """
    Send email notification with voice message transcription and recording link
    
    Args:
        caller_number: Phone number of the caller
        recording_url: URL to the recorded voice message
        transcription_text: Transcribed text of the voice message
        duration_seconds: Duration of the recording in seconds
        language: Language of the message (de/en)
        order_number: Optional order number if available
        
    Returns:
        True if email was sent successfully, False otherwise
    """
    try:
        # Validate input parameters
        if not caller_number or not caller_number.strip():
            logger.warning("Cannot send email: caller_number is empty")
            return False
        
        if not recording_url or not recording_url.strip():
            logger.warning("Cannot send email: recording_url is empty")
            return False
        
        # Check if email is configured
        if not Config.MAIL_RECIPIENT or not Config.MAIL_USERNAME:
            logger.warning("Email not configured. Skipping email send.")
            return False
        
        # Create email message
        msg = MIMEMultipart('alternative')
        
        # Set email headers
        if language == "de":
            subject = f"Neue Sprachnachricht von {caller_number}"
            if order_number:
                subject = f"Neue Sprachnachricht von {caller_number} - Bestellung {order_number}"
        else:
            subject = f"New voice message from {caller_number}"
            if order_number:
                subject = f"New voice message from {caller_number} - Order {order_number}"
        
        msg['Subject'] = subject
        msg['From'] = Config.MAIL_DEFAULT_SENDER or Config.MAIL_USERNAME
        msg['To'] = Config.MAIL_RECIPIENT
        
        # Create email body
        if language == "de":
            text_body = f"""Neue Sprachnachricht erhalten

Anrufer: {caller_number}
Datum/Zeit: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}
Dauer: {duration_seconds} Sekunden
"""
            if order_number:
                text_body += f"Bestellnummer: {order_number}\n"
            
            # Escape HTML special characters for security (XSS prevention)
            safe_transcription = escape(transcription_text) if transcription_text else '(Transkription nicht verfügbar)'
            safe_caller_number = escape(caller_number)
            safe_recording_url = escape(recording_url)
            
            text_body += f"""
Transkription:
{transcription_text if transcription_text else '(Transkription nicht verfügbar)'}

Aufnahme anhören: {recording_url}
"""
            
            html_body = f"""
<html>
  <body>
    <h2>Neue Sprachnachricht erhalten</h2>
    <p><strong>Anrufer:</strong> {safe_caller_number}</p>
    <p><strong>Datum/Zeit:</strong> {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}</p>
    <p><strong>Dauer:</strong> {duration_seconds} Sekunden</p>
"""
            if order_number:
                safe_order_number = escape(str(order_number))
                html_body += f"    <p><strong>Bestellnummer:</strong> {safe_order_number}</p>\n"
            
            html_body += f"""
    <h3>Transkription:</h3>
    <p style="background-color: #f5f5f5; padding: 10px; border-radius: 5px;">
      {safe_transcription}
    </p>
    <p><a href="{safe_recording_url}">Aufnahme anhören</a></p>
  </body>
</html>
"""
        else:
            text_body = f"""New voice message received

Caller: {caller_number}
Date/Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
Duration: {duration_seconds} seconds
"""
            if order_number:
                text_body += f"Order Number: {order_number}\n"
            
            # Escape HTML special characters for security (XSS prevention)
            safe_transcription = escape(transcription_text) if transcription_text else '(Transcription not available)'
            safe_caller_number = escape(caller_number)
            safe_recording_url = escape(recording_url)
            
            text_body += f"""
Transcription:
{transcription_text if transcription_text else '(Transcription not available)'}

Listen to recording: {recording_url}
"""
            
            html_body = f"""
<html>
  <body>
    <h2>New voice message received</h2>
    <p><strong>Caller:</strong> {safe_caller_number}</p>
    <p><strong>Date/Time:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
    <p><strong>Duration:</strong> {duration_seconds} seconds</p>
"""
            if order_number:
                safe_order_number = escape(str(order_number))
                html_body += f"    <p><strong>Order Number:</strong> {safe_order_number}</p>\n"
            
            html_body += f"""
    <h3>Transcription:</h3>
    <p style="background-color: #f5f5f5; padding: 10px; border-radius: 5px;">
      {safe_transcription}
    </p>
    <p><a href="{safe_recording_url}">Listen to recording</a></p>
  </body>
</html>
"""
        
        # Attach both plain text and HTML versions
        charset = getattr(Config, 'EMAIL_CHARSET', 'utf-8')
        part1 = MIMEText(text_body, 'plain', charset)
        part2 = MIMEText(html_body, 'html', charset)
        msg.attach(part1)
        msg.attach(part2)
        
        # Send email
        if Config.MAIL_USE_SSL:
            server = smtplib.SMTP_SSL(Config.MAIL_SERVER, Config.MAIL_PORT)
        else:
            server = smtplib.SMTP(Config.MAIL_SERVER, Config.MAIL_PORT)
            if Config.MAIL_USE_TLS:
                server.starttls()
        
        if Config.MAIL_USERNAME and Config.MAIL_PASSWORD:
            server.login(Config.MAIL_USERNAME, Config.MAIL_PASSWORD)
        
        server.send_message(msg)
        server.quit()
        
        logger.info(f"Email sent successfully to {Config.MAIL_RECIPIENT} for voice message from {caller_number}")
        return True
        
    except Exception as e:
        logger.error(f"Error sending email for voice message: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return False
