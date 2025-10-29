from datetime import datetime


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

    from datetime import date

    promised_date = order_data["promised_delivery_date"]
    if isinstance(promised_date, str):
        promised_date = datetime.strptime(promised_date, "%Y-%m-%d").date()

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
