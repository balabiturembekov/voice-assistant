from datetime import datetime, date
import smtplib
import logging
import re
from html import escape
from urllib.parse import urlparse
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr
from email.header import Header
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


def _validate_email_address(email: str) -> bool:
    """Validate email address format"""
    if not email or not email.strip():
        return False
    # Basic email validation regex
    pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    return bool(re.match(pattern, email.strip()))


def _validate_url(url: str) -> bool:
    """Validate URL format and security"""
    if not url or not url.strip():
        return False
    try:
        parsed = urlparse(url.strip())
        # Only allow http and https protocols
        if parsed.scheme not in ["http", "https"]:
            return False
        # Must have a netloc (domain)
        if not parsed.netloc:
            return False
        # Prevent javascript: and data: URLs
        if parsed.scheme in ["javascript", "data"]:
            return False
        return True
    except Exception:
        return False


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
    server = None
    try:
        # Validate input parameters
        if not caller_number or not caller_number.strip():
            logger.warning("Cannot send email: caller_number is empty")
            return False

        # Validate and sanitize recording_url
        recording_url = recording_url.strip()
        if not recording_url:
            logger.warning("Cannot send email: recording_url is empty")
            return False

        if not _validate_url(recording_url):
            logger.warning(
                f"Cannot send email: recording_url is invalid or unsafe: {recording_url[:50]}"
            )
            return False

        # Validate duration_seconds
        try:
            duration_seconds = int(duration_seconds)
            if duration_seconds < 0:
                logger.warning(
                    f"Cannot send email: duration_seconds is negative: {duration_seconds}"
                )
                duration_seconds = 0
            # Limit maximum duration to prevent DoS
            if duration_seconds > 3600:  # 1 hour max
                logger.warning(
                    f"Cannot send email: duration_seconds exceeds maximum: {duration_seconds}"
                )
                return False
        except (ValueError, TypeError):
            logger.warning(
                f"Cannot send email: duration_seconds is invalid: {duration_seconds}"
            )
            duration_seconds = 0

        # Validate and limit transcription_text length (prevent DoS)
        if transcription_text:
            transcription_text = transcription_text.strip()
            max_transcription_length = 10000  # 10KB max
            if len(transcription_text) > max_transcription_length:
                logger.warning(
                    f"Transcription text too long ({len(transcription_text)} chars), truncating to {max_transcription_length}"
                )
                transcription_text = (
                    transcription_text[:max_transcription_length] + "... [truncated]"
                )

        # Validate email configuration
        if not Config.MAIL_RECIPIENT or not Config.MAIL_USERNAME:
            logger.warning("Email not configured. Skipping email send.")
            return False

        # Validate MAIL_SERVER is configured
        if not Config.MAIL_SERVER:
            logger.error("MAIL_SERVER is not configured. Cannot send email.")
            return False

        # Validate email addresses
        if not _validate_email_address(Config.MAIL_RECIPIENT):
            logger.error(
                f"Invalid MAIL_RECIPIENT email address: {Config.MAIL_RECIPIENT}"
            )
            return False

        sender_email = Config.MAIL_DEFAULT_SENDER or Config.MAIL_USERNAME
        if not sender_email or not sender_email.strip():
            logger.error("Sender email address is empty. Cannot send email.")
            return False

        if not _validate_email_address(sender_email):
            logger.error(f"Invalid sender email address: {sender_email}")
            return False

        # Create email message
        msg = MIMEMultipart("alternative")

        # Set charset for email headers
        charset = getattr(Config, "EMAIL_CHARSET", "utf-8")
        msg.set_charset(charset)

        # Set email headers
        if language == "de":
            subject = f"Neue Sprachnachricht von {caller_number}"
            if order_number:
                subject = f"Neue Sprachnachricht von {caller_number} - Bestellung {order_number}"
        else:
            subject = f"New voice message from {caller_number}"
            if order_number:
                subject = (
                    f"New voice message from {caller_number} - Order {order_number}"
                )

        # Set Subject header with proper UTF-8 encoding
        msg["Subject"] = Header(subject, charset)
        msg["From"] = formataddr(("Voice Assistant", sender_email))
        msg["To"] = Config.MAIL_RECIPIENT

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
            safe_transcription = (
                escape(transcription_text)
                if transcription_text
                else "(Transkription nicht verfügbar)"
            )
            safe_caller_number = escape(caller_number)
            safe_recording_url = escape(recording_url)

            text_body += f"""
Transkription:
{transcription_text if transcription_text else '(Transkription nicht verfügbar)'}

Aufnahme anhören: {recording_url}
"""

            html_body = f"""
<html>
  <head>
    <meta charset="utf-8">
  </head>
  <body>
    <h2>Neue Sprachnachricht erhalten</h2>
    <p><strong>Anrufer:</strong> {safe_caller_number}</p>
    <p><strong>Datum/Zeit:</strong> {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}</p>
    <p><strong>Dauer:</strong> {duration_seconds} Sekunden</p>
"""
            if order_number:
                safe_order_number = escape(str(order_number))
                html_body += (
                    f"    <p><strong>Bestellnummer:</strong> {safe_order_number}</p>\n"
                )

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
            safe_transcription = (
                escape(transcription_text)
                if transcription_text
                else "(Transcription not available)"
            )
            safe_caller_number = escape(caller_number)
            safe_recording_url = escape(recording_url)

            text_body += f"""
Transcription:
{transcription_text if transcription_text else '(Transcription not available)'}

Listen to recording: {recording_url}
"""

            html_body = f"""
<html>
  <head>
    <meta charset="utf-8">
  </head>
  <body>
    <h2>New voice message received</h2>
    <p><strong>Caller:</strong> {safe_caller_number}</p>
    <p><strong>Date/Time:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
    <p><strong>Duration:</strong> {duration_seconds} seconds</p>
"""
            if order_number:
                safe_order_number = escape(str(order_number))
                html_body += (
                    f"    <p><strong>Order Number:</strong> {safe_order_number}</p>\n"
                )

            html_body += f"""
    <h3>Transcription:</h3>
    <p style="background-color: #f5f5f5; padding: 10px; border-radius: 5px;">
      {safe_transcription}
    </p>
    <p><a href="{safe_recording_url}">Listen to recording</a></p>
  </body>
</html>
"""

        # Attach both plain text and HTML versions with explicit charset
        # charset already set above, reuse it
        part1 = MIMEText(text_body, "plain", charset)
        part2 = MIMEText(html_body, "html", charset)
        # Ensure charset is explicitly set in Content-Type headers
        part1.set_charset(charset)
        part2.set_charset(charset)
        msg.attach(part1)
        msg.attach(part2)

        # Send email with proper error handling and timeout
        try:
            # Set timeout for SMTP operations (30 seconds)
            timeout = 30

            # HELO hostname handling
            # IMPORTANT: SMTP servers require HELO to match the actual connecting hostname/IP
            #
            # ⚠️  ОГРАНИЧЕНИЕ: Этот фикс:
            # ✅ уберёт HELO mismatch
            # ✅ снизит spam-score
            # ❌ НЕ заменяет PTR / SPF / DKIM записи
            #
            # Если PTR запись для IP адреса отсутствует (unknown[IP]), некоторые серверы
            # всё равно будут отказывать. Для полного решения нужно:
            # 1. Настроить PTR запись для IP адреса (обратный DNS)
            # 2. Настроить SPF запись в DNS
            # 3. Настроить DKIM подпись
            # 4. Связаться с администратором почтового сервера для настройки
            #
            # Если мы подключаемся с IP, который не имеет PTR записи, лучше не указывать
            # local_hostname вообще - пусть Python использует системный hostname
            import socket

            # Try to get system hostname first
            # Use gethostname() only, as getfqdn() may return incorrect values
            try:
                system_hostname = socket.gethostname()
                # Validate hostname - should not be an IP address or reverse DNS
                # If it looks like an IP or reverse DNS, use None instead
                if system_hostname and (
                    system_hostname.startswith("1.0.0.0")
                    or ".ip6.arpa" in system_hostname
                    or ".in-addr.arpa" in system_hostname
                    or system_hostname.count(".") > 5  # Likely an IP or reverse DNS
                ):
                    logger.warning(
                        f"System hostname looks invalid: {system_hostname}, using None"
                    )
                    system_hostname = None
            except:
                system_hostname = None

            # Use MAIL_HELO_HOSTNAME if explicitly set, otherwise don't specify local_hostname
            # Not specifying local_hostname lets Python use the system default, which usually
            # works better and matches the actual connecting IP/hostname
            helo_hostname = getattr(Config, "MAIL_HELO_HOSTNAME", None)
            if helo_hostname and helo_hostname.strip():
                # MAIL_HELO_HOSTNAME is explicitly set - use it
                helo_hostname = helo_hostname.strip()
                logger.info(f"Using MAIL_HELO_HOSTNAME as HELO: {helo_hostname}")
            else:
                # Don't specify local_hostname - let Python use system default
                # This is usually better because Python will use the appropriate hostname
                # that matches the actual connecting IP/hostname
                helo_hostname = None
                logger.info(
                    "Not specifying local_hostname - letting Python use system default"
                )
                logger.info(
                    "This allows Python to automatically determine the correct HELO hostname "
                    "that matches the actual connecting IP/hostname"
                )

            # Create SMTP connection
            # If helo_hostname is None, don't specify local_hostname parameter
            if Config.MAIL_USE_SSL:
                if helo_hostname:
                    server = smtplib.SMTP_SSL(
                        Config.MAIL_SERVER,
                        Config.MAIL_PORT,
                        timeout=timeout,
                        local_hostname=helo_hostname,
                    )
                else:
                    server = smtplib.SMTP_SSL(
                        Config.MAIL_SERVER, Config.MAIL_PORT, timeout=timeout
                    )
            else:
                if helo_hostname:
                    server = smtplib.SMTP(
                        Config.MAIL_SERVER,
                        Config.MAIL_PORT,
                        timeout=timeout,
                        local_hostname=helo_hostname,
                    )
                else:
                    server = smtplib.SMTP(
                        Config.MAIL_SERVER, Config.MAIL_PORT, timeout=timeout
                    )
                if Config.MAIL_USE_TLS:
                    server.starttls()

            # Send EHLO (Python will use appropriate hostname automatically)
            try:
                if helo_hostname:
                    server.ehlo(helo_hostname)
                else:
                    server.ehlo()  # Use system default
            except Exception as ehlo_error:
                logger.warning(f"EHLO failed, trying default: {str(ehlo_error)}")
                try:
                    server.ehlo()  # Fallback to default
                except Exception as ehlo_error2:
                    logger.error(f"EHLO completely failed: {str(ehlo_error2)}")
                    # Continue anyway - some servers are lenient

            # Authenticate if credentials are provided
            if Config.MAIL_USERNAME and Config.MAIL_PASSWORD:
                try:
                    server.login(Config.MAIL_USERNAME, Config.MAIL_PASSWORD)
                except smtplib.SMTPAuthenticationError as auth_error:
                    logger.error(f"SMTP authentication failed: {str(auth_error)}")
                    return False
                except Exception as auth_error:
                    logger.error(f"SMTP login error: {str(auth_error)}")
                    return False

            # Send message
            try:
                server.send_message(msg)
                logger.info(
                    f"Email sent successfully to {Config.MAIL_RECIPIENT} for voice message from {caller_number} "
                    f"(duration: {duration_seconds}s, order: {order_number or 'N/A'})"
                )
                return True
            except smtplib.SMTPRecipientsRefused as recipients_error:
                error_msg = str(recipients_error)
                logger.error(f"SMTP recipients refused: {error_msg}")
                # Check if it's a rate limiting error
                if (
                    "temporarily blocked" in error_msg.lower()
                    or "retrying too fast" in error_msg.lower()
                ):
                    logger.warning(
                        "SMTP rate limiting detected. Email will be retried later. "
                        "Consider reducing email sending frequency or using email queue."
                    )
                # Check if it's a HELO/hostname mismatch error
                elif (
                    "helo" in error_msg.lower()
                    or "hostname mismatch" in error_msg.lower()
                    or "spam or forged" in error_msg.lower()
                ):
                    logger.error(
                        f"SMTP HELO/hostname mismatch detected. "
                        f"Current HELO hostname: {helo_hostname or 'system default'}. "
                        f"Error: {error_msg[:200]}"
                    )
                    logger.warning(
                        "⚠️  IMPORTANT: This may require DNS configuration:\n"
                        "   1. PTR record (reverse DNS) for your IP address\n"
                        "   2. SPF record in DNS\n"
                        "   3. DKIM signature\n"
                        "   4. Contact your mail server administrator to configure these records.\n"
                        "   This fix only addresses HELO mismatch, but PTR/SPF/DKIM are still required.\n"
                        "   See EMAIL_DNS_SETUP.md for details."
                    )
                return False
            except smtplib.SMTPSenderRefused as sender_error:
                logger.error(f"SMTP sender refused: {str(sender_error)}")
                return False
            except smtplib.SMTPDataError as data_error:
                logger.error(f"SMTP data error: {str(data_error)}")
                return False
            except Exception as send_error:
                logger.error(f"SMTP send error: {str(send_error)}")
                return False
            finally:
                # Always close the connection, even if send failed
                # Check if server was initialized before trying to close it
                if server is not None:
                    try:
                        server.quit()
                    except Exception as quit_error:
                        logger.warning(
                            f"Error closing SMTP connection: {str(quit_error)}"
                        )
                        try:
                            server.close()
                        except Exception:
                            pass

        except smtplib.SMTPConnectError as connect_error:
            logger.error(f"SMTP connection error: {str(connect_error)}")
            return False
        except smtplib.SMTPException as smtp_error:
            logger.error(f"SMTP error: {str(smtp_error)}")
            return False
        except Exception as smtp_error:
            logger.error(f"Unexpected SMTP error: {str(smtp_error)}")
            import traceback

            logger.error(traceback.format_exc())
            return False

    except Exception as e:
        logger.error(f"Error sending email for voice message: {str(e)}")
        import traceback

        logger.error(traceback.format_exc())
        return False
