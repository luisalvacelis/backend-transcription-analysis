from typing import Optional
from uuid import UUID

from fastapi import (
    APIRouter, BackgroundTasks, Depends, File, Form,
    HTTPException, Query, UploadFile, status
)
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.components.connection import get_db
from app.components.models import Audio, Campaign
from app.components.schemas import (
    AudioResponse,
    AudioPage,
    MessageResponse,
    AudioUpdateRequest,
)
from app.dependencies.auth_deps import CurrentUser
from app.services.audio_service import AudioRepository, CampaignRepository
from app.services.storage_service import UploadService
from app.services.deepgram_service import DeepgramService
from app.services.whisperx_service import WhisperXService
from app.utils.extra_utils import DateTimeUtils
from app.utils.file_utils import FileUtils

router = APIRouter()

deepgram_service = DeepgramService()
_whisperx_service: Optional[WhisperXService] = None


def get_whisperx_service() -> WhisperXService:
    global _whisperx_service
    if _whisperx_service is None:
        try:
            _whisperx_service = WhisperXService()
        except Exception as e:
            DateTimeUtils.log(f'Error inicializando WhisperX: {e}', level='ERROR')
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail='WhisperX no disponible'
            )
    return _whisperx_service


def _build_audio_create_payload(file_info: dict) -> dict:
    return {
        'audio_name': file_info['audio_name'],
        'minutes': float(file_info.get('minutes') or 0),
    }


# ─── Background task ─────────────────────────────────────────────────────────

def _process_transcription(audio_id: UUID, provider: str, user_id: UUID) -> None:
    """Tarea en segundo plano: transcribe un audio y guarda el resultado."""
    db = None
    audio = None
    try:
        from app.components.connection import SessionLocal
        db = SessionLocal()

        audio = AudioRepository.get_by_user_and_id(db, user_id, audio_id)
        if not audio:
            DateTimeUtils.log(f'Audio {audio_id} no encontrado para transcribir', level='ERROR')
            return

        DateTimeUtils.log(f'Iniciando transcripción: audio={audio_id}, provider={provider}')

        if provider == 'whisperx':
            service = get_whisperx_service()
            service.process_audio(audio, db)
        else:
            deepgram_service.process_audio(audio, db)

        DateTimeUtils.log(f'Transcripción completada: audio={audio_id}')

    except Exception as e:
        DateTimeUtils.log(f'Error en transcripción de audio {audio_id}: {e}', level='ERROR')
        if db and audio:
            try:
                db.refresh(audio)
                db.commit()
            except Exception:
                pass
    finally:
        if db:
            db.close()


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get('/', response_model=AudioPage, summary='Listar audios')
def list_audios(
    user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    campaign_id: Optional[UUID] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db)
):
    AudioRepository.backfill_missing_minutes(db, user.id)  # type: ignore[arg-type]
    items, meta = AudioRepository.get_paginated(
        db,
        user_id=user.id,  # type: ignore
        page=page,
        page_size=page_size,
        campaign_id=campaign_id,
        search=search
    )
    return AudioPage(items=items, meta=meta)  # type: ignore


@router.get('/stats/summary', summary='Estadísticas de audios del usuario')
def get_stats(user: CurrentUser, db: Session = Depends(get_db)):
    AudioRepository.backfill_missing_minutes(db, user.id)  # type: ignore[arg-type]
    total = AudioRepository.count_by_user(db, user.id)  # type: ignore
    total_cost = AudioRepository.get_total_cost(db, user.id)  # type: ignore
    total_duration_minutes = (
        db.query(func.sum(Audio.minutes))
        .join(Campaign, Campaign.id == Audio.campaign_id)
        .filter(Campaign.user_id == user.id)
        .scalar() or 0.0
    )
    transcribed = (
        db.query(func.count(Audio.id))
        .join(Campaign, Campaign.id == Audio.campaign_id)
        .filter(Campaign.user_id == user.id, Audio.transcription.isnot(None))
        .scalar() or 0
    )
    pending = max(total - int(transcribed), 0)
    return {
        'total': total,
        'transcribed': int(transcribed),
        'pending': pending,
        'total_cost': total_cost,
        'total_duration_minutes': float(total_duration_minutes),
    }


@router.get('/{audio_id}', response_model=AudioResponse, summary='Obtener audio')
def get_audio(
    audio_id: UUID,
    user: CurrentUser,
    db: Session = Depends(get_db)
):
    audio = AudioRepository.get_by_user_and_id(db, user.id, audio_id)  # type: ignore

    if not audio:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail='Audio no encontrado'
        )

    return audio


@router.post('/upload', response_model=AudioResponse, status_code=status.HTTP_201_CREATED, summary='Subir audio')
async def upload_audio(
    user: CurrentUser,
    file: UploadFile = File(...),
    campaign_id: UUID = Form(...),
    db: Session = Depends(get_db)
):
    campaign = CampaignRepository.get_by_id(db, campaign_id, user.id)  # type: ignore
    if not campaign:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail='Campaña no encontrada'
        )

    try:
        file_info = await UploadService.save_file(file, user.id, validate_extension=True)  # type: ignore

        audio = AudioRepository.create(
            db,
            campaign_id=campaign_id,
            **_build_audio_create_payload(file_info)
        )

        DateTimeUtils.log(f'Audio subido: {audio.id} - {audio.audio_name}')
        return audio

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except IOError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Error guardando archivo'
        )


@router.post('/upload-multiple', summary='Subir múltiples audios')
async def upload_multiple_audios(
    user: CurrentUser,
    files: list[UploadFile] = File(...),
    campaign_id: UUID = Form(...),
    db: Session = Depends(get_db)
):
    campaign = CampaignRepository.get_by_id(db, campaign_id, user.id)  # type: ignore
    if not campaign:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail='Campaña no encontrada'
        )

    files_info = await UploadService.save_files(files, user.id)  # type: ignore

    audios = []
    for file_info in files_info:
        audio = AudioRepository.create(
            db,
            campaign_id=campaign_id,
            **_build_audio_create_payload(file_info)
        )
        audios.append(audio)

    DateTimeUtils.log(f'{len(audios)} audios subidos a campaña {campaign_id} por usuario {user.id}')

    return {
        'message': f'{len(audios)} archivos subidos correctamente',
        'audios': audios
    }


@router.post('/{audio_id}/transcribe', response_model=MessageResponse, summary='Transcribir audio individual')
async def transcribe_audio(
    audio_id: UUID,
    user: CurrentUser,
    background_tasks: BackgroundTasks,
    provider: str = Query('deepgram', description='Proveedor: deepgram o whisperx'),
    db: Session = Depends(get_db)
):
    audio = AudioRepository.get_by_user_and_id(db, user.id, audio_id)  # type: ignore

    if not audio:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail='Audio no encontrado'
        )

    if audio.transcription is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='El audio ya tiene una transcripción. Elimínala antes de volver a transcribir.'
        )

    if provider not in ['deepgram', 'whisperx']:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='Provider debe ser "deepgram" o "whisperx"'
        )

    background_tasks.add_task(
        _process_transcription,
        audio_id=audio_id,
        provider=provider,
        user_id=user.id  # type: ignore
    )

    return MessageResponse(
        message='Audio agregado a la cola de transcripción',
        detail=f'Provider: {provider}. Se procesará en segundo plano.'
    )


@router.delete('/{audio_id}', response_model=MessageResponse, summary='Eliminar audio')
def delete_audio(
    audio_id: UUID,
    user: CurrentUser,
    db: Session = Depends(get_db)
):
    audio = AudioRepository.get_by_user_and_id(db, user.id, audio_id)  # type: ignore

    if not audio:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail='Audio no encontrado'
        )

    AudioRepository.delete(db, audio)

    DateTimeUtils.log(f'Audio eliminado: {audio_id}')

    return MessageResponse(
        message='Audio eliminado correctamente',
        detail=None
    )


@router.put('/{audio_id}', response_model=AudioResponse, summary='Actualizar audio')
def update_audio(
    audio_id: UUID,
    data: AudioUpdateRequest,
    user: CurrentUser,
    db: Session = Depends(get_db)
):
    audio = AudioRepository.get_by_user_and_id(db, user.id, audio_id)  # type: ignore
    if not audio:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail='Audio no encontrado'
        )

    update_data = data.model_dump(exclude_unset=True)
    if not update_data:
        return audio

    if 'audio_name' in update_data:
        update_data['audio_name'] = str(update_data['audio_name']).strip()
        if not update_data['audio_name']:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail='El nombre del audio es obligatorio'
            )

    updated = AudioRepository.update(db, audio, **update_data)
    DateTimeUtils.log(f'Audio actualizado: {audio_id}')
    return updated


@router.delete('/campaign/{campaign_id}/all', response_model=MessageResponse, summary='Eliminar todos los audios de una campaña')
def delete_all_campaign_audios(
    campaign_id: UUID,
    user: CurrentUser,
    db: Session = Depends(get_db)
):
    campaign = CampaignRepository.get_by_id(db, campaign_id, user.id)  # type: ignore
    if not campaign:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail='Campaña no encontrada'
        )

    audios = AudioRepository.get_all_by_campaign(db, campaign_id)

    if not audios:
        return MessageResponse(
            message='No hay audios para eliminar',
            detail='La campaña no tiene audios'
        )

    count = len(audios)
    for audio in audios:
        AudioRepository.delete(db, audio)

    DateTimeUtils.log(f'{count} audios eliminados de campaña {campaign_id}')

    return MessageResponse(
        message=f'{count} audios eliminados correctamente',
        detail=None
    )
