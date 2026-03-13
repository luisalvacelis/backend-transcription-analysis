import os
import tempfile
from datetime import datetime, timedelta
from typing import Literal


# ─── AudioUtils ──────────────────────────────────────────────────────────────

class AudioUtils:

    @staticmethod
    def reencode_to_wav(input_path: str, *, channels: int = 1, sample_rate: int = 16000) -> str:
        """Re-codifica cualquier audio a WAV mono 16 kHz usando pydub."""
        from pydub import AudioSegment

        fd, output_path = tempfile.mkstemp(suffix='.wav')
        os.close(fd)

        audio = AudioSegment.from_file(input_path)
        audio = audio.set_channels(channels).set_frame_rate(sample_rate).set_sample_width(2)
        audio.export(output_path, format='wav')

        return output_path

    @staticmethod
    def format_seconds(seconds: float, format: Literal['srt', 'vtt'] = 'srt') -> str:
        """Convierte segundos al formato HH:MM:SS.mmm usado en subtítulos."""
        if seconds is None:
            return '00:00:00.000'

        td = timedelta(seconds=seconds)
        hours = td.seconds // 3600
        minutes = (td.seconds % 3600) // 60
        secs = td.seconds % 60
        millis = td.microseconds // 1000

        return f'{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}'


# ─── DeviceUtils ─────────────────────────────────────────────────────────────

class DeviceUtils:

    @staticmethod
    def get_device(device: str = 'auto') -> str:
        """Devuelve 'cuda' si hay GPU disponible, o 'cpu' en caso contrario."""
        if device == 'auto':
            try:
                import torch
                return 'cuda' if torch.cuda.is_available() else 'cpu'
            except ImportError:
                return 'cpu'
        return device

    @staticmethod
    def print_gpu_info() -> None:
        """Imprime información de la GPU si está disponible."""
        try:
            import torch
        except ImportError:
            print('⚠️  torch no instalado. No se puede consultar GPU.')
            return

        if not torch.cuda.is_available():
            print('⚠️  GPU CUDA no disponible. Usando CPU.')
            return

        props = torch.cuda.get_device_properties(0)
        total_vram = props.total_memory / 1e9
        used_vram = torch.cuda.memory_allocated(0) / 1e9
        free_vram = total_vram - used_vram

        print('✅ Información de GPU:')
        print(f'   GPU: {torch.cuda.get_device_name(0)}')
        print(f'   VRAM Total: {total_vram:.2f} GB')
        print(f'   VRAM Usada: {used_vram:.2f} GB')
        print(f'   VRAM Libre: {free_vram:.2f} GB')

    @staticmethod
    def check_whisperx() -> bool:
        """Verifica si whisperx está instalado."""
        try:
            import whisperx  # noqa
            return True
        except ImportError:
            print('❌ WhisperX no encontrado.')
            print('   Instalar con: pip install git+https://github.com/m-bain/whisperx.git')
            return False


# ─── DateTimeUtils ───────────────────────────────────────────────────────────

class DateTimeUtils:

    @staticmethod
    def now() -> datetime:
        return datetime.now()

    @staticmethod
    def format_now(format: str = '%Y-%m-%d %H:%M:%S') -> str:
        return datetime.now().strftime(format)

    @staticmethod
    def format_datetime(dt: datetime, format: str) -> str:
        return dt.strftime(format)

    @staticmethod
    def log(message: str, level: str = 'INFO') -> None:
        timestamp = datetime.now().strftime('%d-%m-%Y %H:%M:%S')
        print(f'[{timestamp}] {level}: {message}')