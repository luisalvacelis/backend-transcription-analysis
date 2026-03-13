import subprocess
from pathlib import Path
from typing import Optional

from app.utils.extra_utils import DateTimeUtils
from app.utils.file_utils import FileUtils


class FFmpegUtils:

    @staticmethod
    def is_available() -> bool:
        """Comprueba si ffmpeg está disponible en el sistema."""
        try:
            result = subprocess.run(
                ['ffmpeg', '-version'],
                capture_output=True,
                timeout=5
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    @staticmethod
    def convert_to_mp3(
        input_path: str,
        output_path: Optional[str] = None,
        *,
        channels: int = 1,
        sample_rate: int = 16000,
        bitrate: str = '128k',
        overwrite: bool = True
    ) -> str:
        """Convierte cualquier audio a MP3 con los parámetros indicados."""
        if not FileUtils.file_exists(input_path):
            raise FileNotFoundError(f'Archivo no encontrado: {input_path}')

        if output_path is None:
            input_file = Path(input_path)
            output_path = str(input_file.with_suffix('.mp3'))

        FileUtils.ensure_directory(str(Path(output_path).parent))

        cmd = [
            'ffmpeg',
            '-i', input_path,
            '-vn',
            '-ac', str(channels),
            '-ar', str(sample_rate),
            '-b:a', bitrate,
        ]

        if overwrite:
            cmd.insert(1, '-y')

        cmd.append(output_path)

        try:
            DateTimeUtils.log(f'Convirtiendo a MP3: {Path(input_path).name}')

            result = subprocess.run(cmd, capture_output=True, timeout=300)

            if result.returncode != 0:
                stderr = result.stderr.decode('utf-8', errors='replace')
                raise RuntimeError(f'FFmpeg falló: {stderr}')

            DateTimeUtils.log(f'Conversión completada: {Path(output_path).name}')
            return output_path

        except subprocess.TimeoutExpired:
            raise RuntimeError('FFmpeg timeout: conversión tomó demasiado tiempo')
        except Exception as e:
            DateTimeUtils.log(f'Error en conversión FFmpeg: {e}', level='ERROR')
            raise

    @staticmethod
    def convert_video_to_audio(
        input_path: str,
        output_path: Optional[str] = None,
        *,
        format: str = 'mp3',
        channels: int = 1,
        sample_rate: int = 16000,
        bitrate: str = '128k'
    ) -> str:
        """Extrae el audio de un archivo de video."""
        if format.lower() == 'mp3':
            return FFmpegUtils.convert_to_mp3(
                input_path, output_path,
                channels=channels, sample_rate=sample_rate, bitrate=bitrate
            )

        if output_path is None:
            output_path = str(Path(input_path).with_suffix(f'.{format}'))

        FileUtils.ensure_directory(str(Path(output_path).parent))

        cmd = [
            'ffmpeg', '-y',
            '-i', input_path,
            '-vn',
            '-ac', str(channels),
            '-ar', str(sample_rate),
            output_path
        ]

        try:
            DateTimeUtils.log(f'Extrayendo audio de video: {Path(input_path).name}')
            result = subprocess.run(cmd, capture_output=True, timeout=300)

            if result.returncode != 0:
                stderr = result.stderr.decode('utf-8', errors='replace')
                raise RuntimeError(f'FFmpeg falló: {stderr}')

            DateTimeUtils.log(f'Audio extraído: {Path(output_path).name}')
            return output_path

        except subprocess.TimeoutExpired:
            raise RuntimeError('FFmpeg timeout')
        except Exception as e:
            DateTimeUtils.log(f'Error extrayendo audio: {e}', level='ERROR')
            raise

    @staticmethod
    def get_duration(file_path: str) -> Optional[float]:
        """Obtiene la duración en segundos de un archivo multimedia."""
        try:
            cmd = [
                'ffprobe', '-v', 'error',
                '-show_entries', 'format=duration',
                '-of', 'default=noprint_wrappers=1:nokey=1',
                file_path
            ]
            result = subprocess.run(cmd, capture_output=True, timeout=10)

            if result.returncode == 0:
                return float(result.stdout.decode('utf-8').strip())
            return None
        except Exception:
            return None

    @staticmethod
    def get_info(file_path: str) -> Optional[dict]:
        """Devuelve metadatos de audio/video usando ffprobe."""
        try:
            cmd = [
                'ffprobe', '-v', 'quiet',
                '-print_format', 'json',
                '-show_format', '-show_streams',
                file_path
            ]
            result = subprocess.run(cmd, capture_output=True, timeout=10)

            if result.returncode == 0:
                import json
                data = json.loads(result.stdout.decode('utf-8'))
                format_info = data.get('format', {})
                streams = data.get('streams', [])
                audio_stream = next(
                    (s for s in streams if s.get('codec_type') == 'audio'), {}
                )
                return {
                    'duration': float(format_info.get('duration', 0)),
                    'size': int(format_info.get('size', 0)),
                    'bitrate': int(format_info.get('bit_rate', 0)),
                    'codec': audio_stream.get('codec_name'),
                    'sample_rate': int(audio_stream.get('sample_rate', 0)),
                    'channels': int(audio_stream.get('channels', 0)),
                }
            return None
        except Exception as e:
            DateTimeUtils.log(f'Error obteniendo info de archivo: {e}', level='WARN')
            return None