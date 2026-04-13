import os
from pathlib import Path
from typing import Any

from deepgram import DeepgramClient

from app.utils.extra_utils import DateTimeUtils


class DeepgramService:
    def __init__(self):
        keys_raw = (os.getenv('DEEPGRAM_KEYS') or '').strip()
        self.api_keys = [key.strip() for key in keys_raw.split(',') if key.strip()]
        if not self.api_keys:
            raise ValueError('DEEPGRAM_KEYS not set')

        self.model = os.getenv('DEEPGRAM_MODEL', 'nova-3').strip()
        self.language = os.getenv('DEEPGRAM_LANGUAGE', 'es').strip()
        self.timeout = float(os.getenv('DEEPGRAM_TIMEOUT', '1800'))
        self.upload_dir = Path(os.getenv('UPLOAD_DIR', './uploads')).resolve()

    def _audio_path(self, audio) -> Path:
        return self.upload_dir / Path(audio.audio_name).name

    @staticmethod
    def _format_speaker_label(value: Any) -> str:
        if value is None:
            return 'SPEAKER_00'
        text = str(value).strip()
        if not text:
            return 'SPEAKER_00'
        if text.upper().startswith('SPEAKER_'):
            return text.upper()
        if text.isdigit():
            return f'SPEAKER_{int(text):02d}'
        return text.upper()

    @staticmethod
    def _format_time(seconds: Any) -> str:
        try:
            total = float(seconds or 0)
            minutes = int(total // 60)
            rem = total - (minutes * 60)
            return f'{minutes:02d}:{rem:06.3f}'
        except Exception:
            return '00:00.000'

    @staticmethod
    def _safe_get(source: Any, key: str, default: Any = None) -> Any:
        if source is None:
            return default
        if isinstance(source, dict):
            return source.get(key, default)
        return getattr(source, key, default)

    def _build_line(self, start_raw: Any, end_raw: Any, speaker_raw: Any, text_raw: Any) -> str:
        text = str(text_raw or '').strip()
        if not text:
            return ''
        start = self._format_time(start_raw)
        end = self._format_time(end_raw)
        speaker = self._format_speaker_label(speaker_raw)
        return f'{start} - {end} | {speaker} | {text}'

    def _extract_transcript(self, response: Any) -> str:
        response_data: dict[str, Any] | None = None
        try:
            if hasattr(response, 'to_dict') and callable(getattr(response, 'to_dict')):
                candidate = response.to_dict()
                if isinstance(candidate, dict):
                    response_data = candidate
        except Exception:
            response_data = None

        utterances = None
        try:
            utterances = response.results.utterances
        except Exception:
            utterances = None

        if utterances:
            parts: list[str] = []
            for utterance in utterances:
                line = self._build_line(
                    self._safe_get(utterance, 'start', 0),
                    self._safe_get(utterance, 'end', 0),
                    self._safe_get(utterance, 'speaker', None),
                    self._safe_get(utterance, 'transcript', ''),
                )
                if line:
                    parts.append(line)
            if parts:
                return '\n'.join(parts)

        if response_data:
            try:
                utterances_data = (
                    response_data.get('results', {})
                    .get('utterances', [])
                )
                parts = []
                for utterance in utterances_data:
                    line = self._build_line(
                        self._safe_get(utterance, 'start', 0),
                        self._safe_get(utterance, 'end', 0),
                        self._safe_get(utterance, 'speaker', None),
                        self._safe_get(utterance, 'transcript', ''),
                    )
                    if line:
                        parts.append(line)
                if parts:
                    return '\n'.join(parts)
            except Exception:
                pass

        paragraphs = None
        try:
            paragraphs = response.results.channels[0].alternatives[0].paragraphs.paragraphs
        except Exception:
            paragraphs = None

        if paragraphs:
            parts = []
            for paragraph in paragraphs:
                line = self._build_line(
                    self._safe_get(paragraph, 'start', 0),
                    self._safe_get(paragraph, 'end', 0),
                    self._safe_get(paragraph, 'speaker', None),
                    self._safe_get(paragraph, 'transcript', ''),
                )
                if line:
                    parts.append(line)
            if parts:
                return '\n'.join(parts)

        if response_data:
            try:
                paragraphs_data = (
                    response_data.get('results', {})
                    .get('channels', [{}])[0]
                    .get('alternatives', [{}])[0]
                    .get('paragraphs', {})
                    .get('paragraphs', [])
                )
                parts = []
                for paragraph in paragraphs_data:
                    line = self._build_line(
                        self._safe_get(paragraph, 'start', 0),
                        self._safe_get(paragraph, 'end', 0),
                        self._safe_get(paragraph, 'speaker', None),
                        self._safe_get(paragraph, 'transcript', ''),
                    )
                    if line:
                        parts.append(line)
                if parts:
                    return '\n'.join(parts)
            except Exception:
                pass

        transcript = ''
        try:
            results = response.results.channels[0].alternatives[0]
            transcript = getattr(results, 'transcript', '') or ''
        except Exception:
            transcript = ''

        if not transcript and response_data:
            try:
                transcript = (
                    response_data.get('results', {})
                    .get('channels', [{}])[0]
                    .get('alternatives', [{}])[0]
                    .get('transcript', '')
                ) or ''
            except Exception:
                transcript = ''

        if transcript:
            # Last fallback keeps contract with TIME | SPEAKER | TRANSCRIPTION format.
            return f'00:00.000 - 00:00.000 | SPEAKER_00 | {str(transcript).strip()}'

        return ''

    def process_audio(self, audio, db):
        audio_path = self._audio_path(audio)
        if not audio_path.exists():
            raise FileNotFoundError(f'Archivo no encontrado: {audio_path}')

        audio_bytes = audio_path.read_bytes()

        last_error: Exception | None = None
        for api_key in self.api_keys:
            try:
                client = DeepgramClient(api_key=api_key, timeout=self.timeout)
                response = client.listen.v1.media.transcribe_file(
                    request=audio_bytes,
                    model=self.model,
                    language=self.language,
                    smart_format=True,
                    utterances=True,
                    diarize=True,
                    request_options={
                        'timeout_in_seconds': int(self.timeout),
                        'max_retries': 3,
                    },
                )

                transcript = self._extract_transcript(response)

                if not transcript:
                    raise ValueError('Deepgram no devolvio transcripcion')

                audio.transcription = transcript
                audio.cost = float(os.getenv('DEEPGRAM_DEFAULT_COST', '0.05'))
                db.commit()
                DateTimeUtils.log(f'Transcripcion Deepgram completada: {audio.id}')
                return
            except Exception as exc:
                last_error = exc
                continue

        raise ValueError(f'Error transcribiendo con Deepgram: {last_error}')