def detect_language(caller_number: str) -> str:
    """
    Detect language based on caller's phone number
    Default to German, English for US/UK numbers
    """

    clean_number = caller_number.replace('+', '').replace(' ', '')
    

    if clean_number.startswith('1'):  # US/Canada
        return 'en'
    elif clean_number.startswith('44'):  # UK
        return 'en'
    else:
        return 'de'


def get_greeting_message(language: str) -> str:
    """
    Get the appropriate greeting message based on language
    """

    if not isinstance(language, str):
        raise ValueError(f"Invalid language: {language}")

    messages = {
        'de': 'Hallo, mein Name ist Lisa. ich bin Ihr automatischer Servicemitarbeiter. Zur Qualitätssicherung können Gespräche aufgezeichnet werden. Drücken Sie 1, wenn Sie zustimmen, oder 2, wenn Sie der Aufzeichnung nicht zustimmen.',
        'en': "Hello, you're speaking with Liza, your voice assistant. May we process your call to improve our service quality?"
        }
    return messages.get(language, messages['de'])


def format_order_number_for_speech(order_number) -> str:
    """
    Format the order number for speech - pronounced as digits
    Example: 1234567890 -> "one two three four five six seven eight nine zero"
    """
    digits = ' '.join(list(str(order_number)))
    return digits


def get_goodbye_message(language='de') -> str:
    """Get consistent goodbye message based on language"""
    if language == 'de':
        return "Wir bedanken uns für Ihren Anruf und stehen bei weiteren Fragen zur Verfügung!"
    else:
        return "Thank you for calling. We are available for any further questions!"