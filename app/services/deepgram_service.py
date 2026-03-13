import os

class DeepgramService:
    def __init__(self):
        self.api_key = os.getenv('DEEPGRAM_KEYS')
        if not self.api_key:
            raise ValueError("DEEPGRAM_KEYS not set")

    def process_audio(self, audio, db):
        # Placeholder: Simular transcripción
        audio.transcription = "Transcripción simulada con Deepgram"
        audio.cost = 0.05
        db.commit()