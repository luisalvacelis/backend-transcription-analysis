import os
from pathlib import Path
from typing import Any

from app.utils.extra_utils import DateTimeUtils, AudioUtils, DeviceUtils  # pyright: ignore[reportMissingImports]


class WhisperXService:
    def __init__(self):
        self.model_size = os.getenv('WHISPERX_MODEL_SIZE', 'medium').strip()
        self.device = DeviceUtils.get_device(os.getenv('WHISPERX_DEVICE', 'auto').strip())
        self.compute_type = os.getenv('WHISPERX_COMPUTE_TYPE', 'float16').strip()
        self.batch_size = int(os.getenv('WHISPERX_BATCH_SIZE', '8'))
        self.language = os.getenv('WHISPERX_LANGUAGE', 'es').strip()
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

    def _build_diarized_transcript(self, whisperx_module: Any, model_result: dict[str, Any], audio_data: Any, wav_path: str) -> str:
        segments = model_result.get('segments') or []
        if not segments:
            return ''

        aligned_result = model_result
        try:
            align_model, align_metadata = whisperx_module.load_align_model(
                language_code=model_result.get('language', self.language),
                device=self.device,
            )
            aligned_result = whisperx_module.align(
                segments,
                align_model,
                align_metadata,
                audio_data,
                self.device,
                return_char_alignments=False,
            )
        except Exception:
            aligned_result = model_result

        transcript_parts: list[str] = []
        try:
            diarize_pipeline = whisperx_module.DiarizationPipeline(
                use_auth_token=os.getenv('HUGGINGFACE_TOKEN', '').strip() or None,
                device=self.device,
            )
            diarize_segments = diarize_pipeline(wav_path)
            assigned = whisperx_module.assign_word_speakers(diarize_segments, aligned_result)
            for segment in assigned.get('segments', []):
                speaker = self._format_speaker_label(segment.get('speaker'))
                start = self._format_time(segment.get('start'))
                end = self._format_time(segment.get('end'))
                text = str(segment.get('text', '') or '').strip()
                if text:
                    transcript_parts.append(f'{start} - {end} | {speaker} | {text}')
        except Exception:
            for segment in aligned_result.get('segments', []):
                speaker = self._format_speaker_label(segment.get('speaker'))
                start = self._format_time(segment.get('start'))
                end = self._format_time(segment.get('end'))
                text = str(segment.get('text', '') or '').strip()
                if text:
                    transcript_parts.append(f'{start} - {end} | {speaker} | {text}')

        return '\n'.join(transcript_parts).strip()

    def process_audio(self, audio, db):
        import whisperx  # pyright: ignore[reportMissingImports]

        audio_path = self._audio_path(audio)
        if not audio_path.exists():
            raise FileNotFoundError(f'Archivo no encontrado: {audio_path}')

        wav_path = AudioUtils.reencode_to_wav(str(audio_path))
        try:
            model = whisperx.load_model(
                self.model_size,
                device=self.device,
                compute_type=self.compute_type,
            )
            audio_data = whisperx.load_audio(wav_path)
            result = model.transcribe(audio_data, batch_size=self.batch_size, language=self.language)
            transcript = self._build_diarized_transcript(whisperx, result, audio_data, wav_path)

            if not transcript:
                raise ValueError('WhisperX no devolvio transcripcion')

            audio.transcription = transcript
            audio.cost = float(os.getenv('WHISPERX_DEFAULT_COST', '0.03'))
            db.commit()
            DateTimeUtils.log(f'Transcripcion WhisperX completada: {audio.id}')
        finally:
            try:
                Path(wav_path).unlink(missing_ok=True)
            except Exception:
                pass