import os
from pathlib import Path
from typing import Optional

from app.utils.extra_utils import DateTimeUtils


class FileUtils:

    @staticmethod
    def safe_delete(file_path: Optional[str]) -> bool:
        if not file_path:
            return False

        try:
            path = Path(file_path)

            if path.exists() and path.is_file():
                path.unlink()
                return True

            return False

        except Exception as e:
            DateTimeUtils.log(f'Error eliminando archivo {file_path}: {e}', level='WARN')
            return False

    @staticmethod
    def safe_delete_multiple(file_paths: list[Optional[str]]) -> int:
        deleted = 0

        for file_path in file_paths:
            if FileUtils.safe_delete(file_path):
                deleted += 1

        return deleted

    @staticmethod
    def ensure_directory(directory: str) -> bool:
        try:
            Path(directory).mkdir(parents=True, exist_ok=True)
            return True
        except Exception as e:
            DateTimeUtils.log(f'Error creando directorio {directory}: {e}', level='ERROR')
            return False

    @staticmethod
    def get_file_size(file_path: str) -> Optional[int]:
        try:
            return Path(file_path).stat().st_size
        except Exception:
            return None

    @staticmethod
    def file_exists(file_path: Optional[str]) -> bool:
        if not file_path:
            return False

        try:
            path = Path(file_path)
            return path.exists() and path.is_file()
        except Exception:
            return False

    @staticmethod
    def get_extension(file_path: str) -> str:
        return Path(file_path).suffix.lower()

    @staticmethod
    def get_filename(file_path: str) -> str:
        return Path(file_path).name

    @staticmethod
    def get_filename_without_extension(file_path: str) -> str:
        return Path(file_path).stem


def safe_delete_file(path: Optional[str]) -> bool:
    return FileUtils.safe_delete(path)