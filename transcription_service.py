#!/usr/bin/env python3
"""
External Transcription Service Integration
Supports Google Cloud Speech-to-Text and Deepgram for accurate German transcription
"""
import logging
import requests
from typing import Optional, Dict
from config import Config

logger = logging.getLogger(__name__)


class TranscriptionService:
    """Base class for external transcription services"""

    def transcribe_audio(
        self, audio_url: str, language: str = "de-DE"
    ) -> Optional[str]:
        """
        Transcribe audio from URL
        
        Args:
            audio_url: URL to audio file
            language: Language code (de-DE, en-US, etc.)
            
        Returns:
            Transcribed text or None if failed
        """
        raise NotImplementedError


class GoogleCloudTranscription(TranscriptionService):
    """
    Google Cloud Speech-to-Text integration
    Requires: pip install google-cloud-speech
    Setup: Set GOOGLE_APPLICATION_CREDENTIALS environment variable or use service account
    """

    def __init__(self):
        try:
            from google.cloud import speech
            self.client = speech.SpeechClient()
            self.enabled = True
            logger.info("Google Cloud Speech-to-Text initialized")
        except ImportError:
            logger.warning(
                "google-cloud-speech not installed. Install with: pip install google-cloud-speech"
            )
            self.enabled = False
        except Exception as e:
            logger.error(f"Failed to initialize Google Cloud Speech-to-Text: {e}")
            self.enabled = False

    def transcribe_audio(
        self, audio_url: str, language: str = "de-DE"
    ) -> Optional[str]:
        """Transcribe audio using Google Cloud Speech-to-Text"""
        if not self.enabled:
            logger.warning("Google Cloud Speech-to-Text is not enabled")
            return None

        try:
            # Download audio from URL
            response = requests.get(audio_url, timeout=30)
            response.raise_for_status()
            audio_content = response.content

            # Configure recognition
            config = speech.RecognitionConfig(
                encoding=speech.RecognitionConfig.AudioEncoding.MP3,  # Twilio uses MP3
                sample_rate_hertz=8000,  # Twilio default
                language_code=language,
                enable_automatic_punctuation=True,
            )

            audio = speech.RecognitionAudio(content=audio_content)

            # Perform transcription
            response = self.client.recognize(config=config, audio=audio)

            # Extract transcript
            if response.results:
                transcript = " ".join(
                    [result.alternatives[0].transcript for result in response.results]
                )
                logger.info(
                    f"Google Cloud transcription successful: {len(transcript)} chars"
                )
                return transcript
            else:
                logger.warning("Google Cloud transcription returned no results")
                return None

        except Exception as e:
            logger.error(f"Google Cloud transcription error: {e}")
            return None


class DeepgramTranscription(TranscriptionService):
    """
    Deepgram API integration
    Requires: DEEPGRAM_API_KEY in environment variables
    Sign up: https://deepgram.com/
    """

    def __init__(self):
        self.api_key = getattr(Config, "DEEPGRAM_API_KEY", None)
        self.api_url = "https://api.deepgram.com/v1/listen"
        self.enabled = bool(self.api_key)
        if not self.enabled:
            logger.warning(
                "Deepgram API key not configured. Set DEEPGRAM_API_KEY environment variable."
            )

    def transcribe_audio(
        self, audio_url: str, language: str = "de-DE"
    ) -> Optional[str]:
        """Transcribe audio using Deepgram API"""
        if not self.enabled:
            logger.warning("Deepgram is not enabled")
            return None

        try:
            # Deepgram language mapping
            language_map = {
                "de-DE": "de",
                "en-US": "en",
            }
            deepgram_lang = language_map.get(language, "de")

            # Make API request
            headers = {
                "Authorization": f"Token {self.api_key}",
            }
            params = {
                "language": deepgram_lang,
                "punctuate": "true",
                "model": "nova-2",  # Use nova-2 or nova-3 for best accuracy
            }

            # Deepgram can transcribe from URL directly
            response = requests.post(
                self.api_url,
                headers=headers,
                params=params,
                json={"url": audio_url},
                timeout=30,
            )
            response.raise_for_status()

            result = response.json()
            if "results" in result and "channels" in result["results"]:
                transcript = result["results"]["channels"][0]["alternatives"][0][
                    "transcript"
                ]
                logger.info(
                    f"Deepgram transcription successful: {len(transcript)} chars"
                )
                return transcript
            else:
                logger.warning("Deepgram transcription returned no results")
                return None

        except Exception as e:
            logger.error(f"Deepgram transcription error: {e}")
            return None


# Factory function to get transcription service
def get_transcription_service(service_name: str = "google") -> TranscriptionService:
    """
    Get transcription service instance
    
    Args:
        service_name: 'google' or 'deepgram'
        
    Returns:
        TranscriptionService instance
    """
    service_name = service_name.lower()
    
    if service_name == "google":
        return GoogleCloudTranscription()
    elif service_name == "deepgram":
        return DeepgramTranscription()
    else:
        logger.warning(f"Unknown transcription service: {service_name}, using Google")
        return GoogleCloudTranscription()


# Convenience function for easy integration
def transcribe_with_external_service(
    audio_url: str, language: str = "de-DE", service: str = "google"
) -> Optional[str]:
    """
    Transcribe audio using external service
    
    Args:
        audio_url: URL to audio file
        language: Language code (de-DE, en-US)
        service: 'google' or 'deepgram'
        
    Returns:
        Transcribed text or None
    """
    transcription_service = get_transcription_service(service)
    return transcription_service.transcribe_audio(audio_url, language)

