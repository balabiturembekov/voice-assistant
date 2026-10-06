"""
Everything Lisa says, per call language. Keep wording here, not in the flow code.

Placeholders are filled with str.format(); numbers are pre-formatted for speech.
"""

PROMPTS = {
    "de": {
        "greeting": (
            "Guten Tag, hier ist Lisa, die digitale Assistentin von {company}. "
            "Informationen zum Datenschutz finden Sie auf unserer Website."
        ),
        "menu": (
            "Für den Status Ihrer Bestellung drücken Sie die Eins. "
            "Um uns eine Nachricht zu hinterlassen, die Zwei. "
            "Für ein Gespräch mit unserem Team die Null."
        ),
        "menu_retry": "Das habe ich leider nicht verstanden.",
        "order_number": (
            "Bitte geben Sie Ihre Bestell- oder Rechnungsnummer ein "
            "und drücken Sie anschließend die Rautetaste."
        ),
        "order_number_retry": "Ich habe leider keine Eingabe erhalten.",
        "not_found_retry": (
            "Unter der Nummer {number} habe ich leider keinen Auftrag gefunden."
        ),
        "not_found_final": (
            "Unter der Nummer {number} habe ich leider wieder keinen Auftrag gefunden."
        ),
        "plz": (
            "Zu Ihrer Sicherheit: Bitte geben Sie die Postleitzahl Ihrer Rechnungsadresse ein "
            "und drücken Sie die Rautetaste."
        ),
        "plz_retry": "Die Postleitzahl stimmt leider nicht überein.",
        "status_shipped": "Ihr Auftrag {number} wurde am {date} versendet.",
        "status_planned": (
            "Ihr Auftrag {number} ist für die Lieferung in Kalenderwoche {weeks} eingeplant, "
            "also zwischen dem {start} und dem {end}."
        ),
        "status_production": (
            "Ihr Auftrag {number} ist in Produktion. "
            "Die Lieferung erwarten wir voraussichtlich zwischen dem {start} und dem {end}."
        ),
        "status_delivery_soon": (
            "Ihr Auftrag {number} ist fertig für die Auslieferung. "
            "Die Lieferung erwarten wir voraussichtlich bis zum {end}."
        ),
        "status_open_amount": "Offen ist noch ein Betrag von {amount}.",
        "status_unverified": (
            "Ihr Auftrag {number} ist in Bearbeitung. "
            "Aus Datenschutzgründen nenne ich weitere Details nur, wenn Sie von der "
            "hinterlegten Telefonnummer anrufen. Gern verbinde ich Sie dafür mit unserem Team."
        ),
        "status_overdue": (
            "Ihre Lieferung verzögert sich leider. Das tut uns sehr leid. "
            "Ich verbinde Sie bevorzugt mit unserem Team."
        ),
        "next_menu": (
            "Zum Wiederholen drücken Sie die Sterntaste, "
            "für einen weiteren Auftrag die Eins, "
            "für eine Nachricht die Zwei, "
            "für unser Team die Null."
        ),
        "not_found_menu": (
            "Für einen neuen Versuch drücken Sie die Eins, "
            "für eine Nachricht die Zwei, "
            "für unser Team die Null."
        ),
        "agent_connecting": "Ich verbinde Sie mit unserem Team. Einen Moment, bitte.",
        "agent_after_hours": (
            "Unser Team ist {hours} erreichbar. Gern nehme ich Ihre Nachricht auf."
        ),
        "agent_no_answer": (
            "Leider ist gerade niemand erreichbar. Gern nehme ich Ihre Nachricht auf."
        ),
        "voicemail": (
            "Bitte sprechen Sie Ihre Nachricht nach dem Signalton und nennen Sie dabei "
            "Ihren Namen und Ihre E-Mail-Adresse. Zum Beenden drücken Sie die Rautetaste."
        ),
        "voicemail_thanks": (
            "Vielen Dank für Ihre Nachricht. Wir antworten Ihnen schnellstmöglich per E-Mail. "
            "Auf Wiederhören!"
        ),
        "voicemail_failed": (
            "Ihre Nachricht konnte ich leider nicht aufnehmen. "
            "Bitte rufen Sie uns noch einmal an."
        ),
        "goodbye": "Vielen Dank für Ihren Anruf. Auf Wiederhören!",
        "error": (
            "Entschuldigung, es ist ein technischer Fehler aufgetreten. "
            "Bitte rufen Sie später noch einmal an."
        ),
    },
    "en": {
        "greeting": (
            "Hello, this is Lisa, the digital assistant of {company}. "
            "You can find our privacy information on our website."
        ),
        "menu": (
            "For the status of your order, press 1. "
            "To leave us a message, press 2. "
            "To speak to our team, press 0."
        ),
        "menu_retry": "Sorry, I didn't catch that.",
        "order_number": "Please enter your order or invoice number, then press the hash key.",
        "order_number_retry": "Sorry, I didn't receive any input.",
        "not_found_retry": (
            "Sorry, I couldn't find an order with the number {number}."
        ),
        "not_found_final": "Sorry, I still couldn't find an order with the number {number}.",
        "plz": (
            "For your security, please enter the postcode of your billing address, "
            "then press the hash key."
        ),
        "plz_retry": "Sorry, the postcode doesn't match.",
        "status_shipped": "Your order {number} was shipped on {date}.",
        "status_planned": (
            "Your order {number} is scheduled for delivery in calendar week {weeks}, "
            "between {start} and {end}."
        ),
        "status_production": (
            "Your order {number} is in production. "
            "We expect delivery between {start} and {end}."
        ),
        "status_delivery_soon": (
            "Your order {number} is ready for delivery. We expect delivery by {end}."
        ),
        "status_open_amount": "An amount of {amount} is still outstanding.",
        "status_unverified": (
            "Your order {number} is being processed. "
            "For privacy reasons, I can only share details when you call from the phone number "
            "on the order. I'm happy to connect you with our team."
        ),
        "status_overdue": (
            "Unfortunately, your delivery is delayed. We are very sorry. "
            "I'll connect you with our team right away."
        ),
        "next_menu": (
            "To repeat, press the star key. "
            "For another order, press 1. "
            "To leave a message, press 2. "
            "To speak to our team, press 0."
        ),
        "not_found_menu": (
            "To try again, press 1. To leave a message, press 2. To speak to our team, press 0."
        ),
        "agent_connecting": "I'm connecting you with our team. One moment, please.",
        "agent_after_hours": "Our team is available {hours}. I'm happy to take a message.",
        "agent_no_answer": "Unfortunately, no one is available right now. I'm happy to take a message.",
        "voicemail": (
            "Please leave your message after the tone, including your name and email address. "
            "Press the hash key when you're done."
        ),
        "voicemail_thanks": "Thank you for your message. We'll reply by email as soon as possible. Goodbye!",
        "voicemail_failed": "Sorry, I couldn't record your message. Please call us again.",
        "goodbye": "Thank you for calling. Goodbye!",
        "error": "Sorry, a technical error occurred. Please call again later.",
    },
}


# Offer to switch language, spoken in the target language: key = current call language
LANGUAGE_SWITCH = {
    "de": ("en", "For English, press 9."),
    "en": ("de", "Für Deutsch drücken Sie die Neun."),
}


def prompt(language, key, **values):
    """Text for a prompt key; unknown languages fall back to German"""
    texts = PROMPTS.get(language, PROMPTS["de"])
    return texts[key].format(**values)
