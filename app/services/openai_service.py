import os

class OpenAIService:
    def __init__(self):
        self.api_key = os.getenv('OPENAI_API_KEY')
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY not set")

    def analyze_transcription(self, transcription: str, custom_prompt: str, audio_key: str):
        # Placeholder: Simular análisis
        return {
            'analysis': [
                {
                    'criterio': 'Claridad',
                    'evaluacion': 'Buena',
                    'justificacion': 'Transcripción clara',
                    'obs_adicional': None
                }
            ],
            'in_tokens': 100,
            'out_tokens': 50,
            'cost': 0.01
        }