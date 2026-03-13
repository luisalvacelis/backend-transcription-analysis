class UploadService:
    @staticmethod
    async def save_file(file, user_id, validate_extension=True):
        # Placeholder
        return {
            'audio_name': file.filename,
            'original_path': f'/uploads/{file.filename}',
            'size_bytes': 1000
        }

    @staticmethod
    async def save_files(files, user_id):
        # Placeholder
        return [{'audio_name': f.filename, 'original_path': f'/uploads/{f.filename}', 'size_bytes': 1000} for f in files]