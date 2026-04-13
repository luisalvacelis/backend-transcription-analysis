import os
import json
import shutil
import subprocess
import wave
from pathlib import Path

from app.utils.extra_utils import DateTimeUtils


class UploadService:
    @staticmethod
    def _upload_dir() -> Path:
        base_dir = Path(os.getenv('UPLOAD_DIR', './uploads')).resolve()
        base_dir.mkdir(parents=True, exist_ok=True)
        return base_dir

    @staticmethod
    def _validate_extension(filename: str) -> None:
        allowed = {'.mp3', '.wav', '.m4a', '.ogg', '.ogm', '.mp4'}
        suffix = Path(filename).suffix.lower()
        if suffix not in allowed:
            raise ValueError('Extension de archivo no permitida')

    @staticmethod
    def get_duration_seconds(file_path: Path) -> float:
        ffprobe_path = shutil.which('ffprobe')
        if ffprobe_path:
            try:
                result = subprocess.run(
                    [
                        ffprobe_path,
                        '-v', 'error',
                        '-show_entries', 'format=duration',
                        '-of', 'json',
                        str(file_path),
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                payload = json.loads(result.stdout or '{}')
                duration = float(payload.get('format', {}).get('duration', 0) or 0)
                if duration > 0:
                    return duration
            except Exception as exc:
                DateTimeUtils.log(f'ffprobe fallo para {file_path.name}: {exc}', level='ERROR')

        if file_path.suffix.lower() == '.wav':
            try:
                with wave.open(str(file_path), 'rb') as audio_file:
                    frame_rate = audio_file.getframerate() or 0
                    total_frames = audio_file.getnframes() or 0
                    if frame_rate > 0 and total_frames > 0:
                        return float(total_frames / frame_rate)
            except Exception as exc:
                DateTimeUtils.log(f'wave fallo para {file_path.name}: {exc}', level='ERROR')

        return 0.0

    @staticmethod
    async def save_file(file, user_id, validate_extension=True):
        filename = Path(file.filename or '').name
        if not filename:
            raise ValueError('Nombre de archivo invalido')

        if validate_extension:
            UploadService._validate_extension(filename)

        upload_dir = UploadService._upload_dir()
        output_path = upload_dir / filename
        content = await file.read()
        output_path.write_bytes(content)

        duration_seconds = UploadService.get_duration_seconds(output_path)

        DateTimeUtils.log(f'Archivo guardado: {output_path}')
        return {
            'audio_name': filename,
            'original_path': str(output_path),
            'size_bytes': len(content),
            'duration_seconds': duration_seconds,
            'minutes': round(duration_seconds / 60.0, 2) if duration_seconds else 0.0,
        }

    @staticmethod
    async def save_files(files, user_id):
        results = []
        for file in files:
            results.append(await UploadService.save_file(file, user_id, validate_extension=True))
        return results
