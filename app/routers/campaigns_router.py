from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from typing import Optional
from uuid import UUID

from app.components.connection import get_db
from app.components.schemas import (
    CampaignCreate,
    CampaignUpdate,
    CampaignResponse,
    CampaignPage,
    MessageResponse,
    CampaignTranscribeRequest,
    CampaignAnalysisRequest,
)
from app.dependencies.auth_deps import CurrentUser
from app.services.audio_service import CampaignRepository, AudioRepository
from app.services.analysis_service import AnalysisRepository
from app.utils.extra_utils import DateTimeUtils

# In-memory job tracker: { campaign_id (str): { cancelled, total, completed, failed } }
transcription_jobs: dict[str, dict] = {}

router = APIRouter()


# ─── CRUD básico ──────────────────────────────────────────────────────────────

@router.post('/', response_model=CampaignResponse, status_code=status.HTTP_201_CREATED, summary='Crear campaña')
def create_campaign(
    data: CampaignCreate,
    user: CurrentUser,
    db: Session = Depends(get_db)
):
    existing = CampaignRepository.get_by_name(db, data.campaign_name, user.id)  # type: ignore[arg-type]
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='Ya existe una campaña con ese nombre'
        )
    campaign = CampaignRepository.create(
        db,
        user_id=user.id,  # type: ignore[arg-type]
        campaign_name=data.campaign_name,
        description=data.description
    )
    DateTimeUtils.log(f'Campaña creada por usuario {user.id}: {campaign.campaign_name}')
    return campaign


@router.get('/', response_model=CampaignPage, summary='Listar campañas')
def list_campaigns(
    user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    search: Optional[str] = None,
    db: Session = Depends(get_db)
):
    items, meta = CampaignRepository.get_paginated(
        db,
        user_id=user.id,  # type: ignore[arg-type]
        page=page,
        page_size=page_size,
        search=search
    )
    return CampaignPage(items=items, meta=meta)  # type: ignore[arg-type]


@router.get('/with-stats', summary='Listar campañas con estadísticas')
def list_campaigns_with_stats(
    user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    search: Optional[str] = None,
    db: Session = Depends(get_db)
):
    campaigns, meta = CampaignRepository.get_paginated(
        db,
        user_id=user.id,  # type: ignore[arg-type]
        page=page,
        page_size=page_size,
        search=search
    )

    results = []
    for campaign in campaigns:
        stats = CampaignRepository.get_campaign_stats(db, campaign.id, user.id)  # type: ignore[arg-type]

        total_audios: int = stats['total_audios']
        transcribed: int = stats['transcribed']
        pending: int = stats['pending']

        if total_audios == 0:
            status_text = 'EMPTY'
        elif transcribed == total_audios:
            status_text = 'COMPLETED'
        elif transcribed > 0:
            status_text = 'PARTIAL'
        else:
            status_text = 'PENDING'

        last_audio_update = AudioRepository.get_last_updated_audio(db, campaign.id, user.id)  # type: ignore[arg-type]

        # Resolvemos updated_date con comparaciones explícitas contra None
        # para evitar el warning de Pylance sobre Column[datetime] como booleano
        register_date_str: str = campaign.register_date.isoformat()  # type: ignore[union-attr]
        updated_date_str: str
        if last_audio_update is not None:
            updated_date_str = last_audio_update.isoformat()
        elif campaign.updated_date is not None:  # type: ignore[union-attr]
            updated_date_str = campaign.updated_date.isoformat()  # type: ignore[union-attr]
        else:
            updated_date_str = register_date_str

        results.append({
            'id': str(campaign.id),
            'campaign_name': campaign.campaign_name,
            'description': campaign.description,
            'total_audios': total_audios,
            'transcribed': transcribed,
            'pending': pending,
            'status': status_text,
            'total_cost': stats['total_cost'],
            'total_duration_minutes': stats['total_duration_minutes'],
            'register_date': register_date_str,
            'updated_date': updated_date_str,
        })

    return {'items': results, 'meta': meta}


@router.get('/{campaign_id}', response_model=CampaignResponse, summary='Obtener campaña')
def get_campaign(
    campaign_id: UUID,
    user: CurrentUser,
    db: Session = Depends(get_db)
):
    campaign = CampaignRepository.get_by_id(db, campaign_id, user.id)  # type: ignore[arg-type]
    if not campaign:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail='Campaña no encontrada'
        )
    return campaign


@router.put('/{campaign_id}', response_model=CampaignResponse, summary='Actualizar campaña')
def update_campaign(
    campaign_id: UUID,
    data: CampaignUpdate,
    user: CurrentUser,
    db: Session = Depends(get_db)
):
    campaign = CampaignRepository.get_by_id(db, campaign_id, user.id)  # type: ignore[arg-type]
    if not campaign:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail='Campaña no encontrada'
        )

    if data.campaign_name:
        existing = CampaignRepository.get_by_name(db, data.campaign_name, user.id)  # type: ignore[arg-type]
        if existing and existing.id != campaign_id:  # type: ignore[union-attr]
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail='Ya existe una campaña con ese nombre'
            )

    update_data = data.model_dump(exclude_unset=True)
    campaign = CampaignRepository.update(db, campaign, **update_data)

    DateTimeUtils.log(f'Campaña actualizada por usuario {user.id}: {campaign.campaign_name}')
    return campaign


@router.delete('/{campaign_id}', response_model=MessageResponse, summary='Eliminar campaña')
def delete_campaign(
    campaign_id: UUID,
    user: CurrentUser,
    db: Session = Depends(get_db)
):
    campaign = CampaignRepository.get_by_id(db, campaign_id, user.id)  # type: ignore[arg-type]
    if not campaign:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail='Campaña no encontrada'
        )

    audios = AudioRepository.get_all_by_campaign(db, campaign_id)
    for audio in audios:
        AudioRepository.delete(db, audio)

    CampaignRepository.delete(db, campaign)

    DateTimeUtils.log(
        f'Campaña eliminada por usuario {user.id}: {campaign.campaign_name} '
        f'({len(audios)} audios eliminados)'
    )
    return MessageResponse(
        message='Campaña eliminada correctamente',
        detail=f'{len(audios)} audios eliminados'
    )


@router.get('/{campaign_id}/stats', summary='Estadísticas de campaña')
def get_campaign_stats(
    campaign_id: UUID,
    user: CurrentUser,
    db: Session = Depends(get_db),
):
    campaign = CampaignRepository.get_by_id(db, campaign_id, user.id)  # type: ignore[arg-type]
    if not campaign:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail='Campaña no encontrada'
        )

    stats = CampaignRepository.get_campaign_stats(db, campaign_id, user.id)  # type: ignore[arg-type]

    return {
        'campaign_id': campaign_id,
        'campaign_name': campaign.campaign_name,
        'user_id': user.id,
        **stats
    }


# ─── Transcripción masiva ─────────────────────────────────────────────────────

def _process_campaign_transcription(campaign_id: UUID, provider: str, user_id: UUID) -> None:
    """Tarea en segundo plano: transcribe todos los audios pendientes de una campaña."""
    db = None
    job_key = str(campaign_id)
    try:
        from app.components.connection import SessionLocal
        db = SessionLocal()

        audios = AudioRepository.get_all_by_campaign_without_transcription(db, campaign_id)

        transcription_jobs[job_key] = {
            'cancelled': False,
            'total': len(audios),
            'completed': 0,
            'failed': 0,
        }

        for audio in audios:
            if transcription_jobs[job_key]['cancelled']:
                DateTimeUtils.log(f'Transcripción de campaña {campaign_id} cancelada')
                break

            DateTimeUtils.log(f'Transcribiendo audio {audio.id}: {audio.audio_name}')

            try:
                if provider == 'whisperx':
                    from app.services.whisperx_service import WhisperXService
                    service = WhisperXService()
                    service.process_audio(audio, db)
                else:
                    from app.services.deepgram_service import DeepgramService
                    service = DeepgramService()
                    service.process_audio(audio, db)

                transcription_jobs[job_key]['completed'] += 1
                DateTimeUtils.log(f'Audio {audio.id} transcrito exitosamente')

            except Exception as e:
                DateTimeUtils.log(f'Error transcribiendo audio {audio.id}: {e}', level='ERROR')
                transcription_jobs[job_key]['failed'] += 1

        DateTimeUtils.log(f'Transcripción de campaña {campaign_id} finalizada')

    except Exception as e:
        DateTimeUtils.log(f'Error en transcripción masiva de campaña {campaign_id}: {e}', level='ERROR')
    finally:
        if db:
            db.close()


@router.post('/{campaign_id}/transcribe-all', summary='Transcribir todos los audios pendientes de la campaña')
def transcribe_all_audios(
    campaign_id: UUID,
    data: CampaignTranscribeRequest,
    background_tasks: BackgroundTasks,
    user: CurrentUser,
    db: Session = Depends(get_db)
):
    campaign = CampaignRepository.get_by_id(db, campaign_id, user.id)  # type: ignore[arg-type]
    if not campaign:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail='Campaña no encontrada'
        )

    audios = AudioRepository.get_all_by_campaign_without_transcription(db, campaign_id)
    if not audios:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='No hay audios pendientes de transcripción en esta campaña'
        )

    background_tasks.add_task(
        _process_campaign_transcription,
        campaign_id=campaign_id,
        provider=data.provider,
        user_id=user.id  # type: ignore[arg-type]
    )

    DateTimeUtils.log(
        f'Usuario {user.id} solicitó transcribir {len(audios)} audios '
        f'de campaña {campaign.campaign_name} con {data.provider}'
    )

    return {
        'message': f'Iniciando transcripción de {len(audios)} audios',
        'campaign_id': campaign_id,
        'campaign_name': campaign.campaign_name,
        'total_audios': len(audios),
        'provider': data.provider,
    }


@router.post('/{campaign_id}/transcribe-stop', summary='Detener transcripción activa de la campaña')
def stop_transcription(
    campaign_id: UUID,
    user: CurrentUser,
    db: Session = Depends(get_db)
):
    campaign = CampaignRepository.get_by_id(db, campaign_id, user.id)  # type: ignore[arg-type]
    if not campaign:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail='Campaña no encontrada'
        )

    job_key = str(campaign_id)
    if job_key not in transcription_jobs:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='No hay transcripción activa para esta campaña'
        )

    transcription_jobs[job_key]['cancelled'] = True
    DateTimeUtils.log(f'Usuario {user.id} detuvo transcripción de campaña {campaign.campaign_name}')

    return {
        'message': 'Transcripción detenida',
        'campaign_id': campaign_id,
        'campaign_name': campaign.campaign_name,
        'detail': 'Los audios ya transcritos se mantienen; los pendientes permanecen sin transcripción.',
    }


@router.get('/{campaign_id}/transcribe-status', summary='Ver progreso de transcripción')
def get_transcription_status(
    campaign_id: UUID,
    user: CurrentUser,
    db: Session = Depends(get_db)
):
    campaign = CampaignRepository.get_by_id(db, campaign_id, user.id)  # type: ignore[arg-type]
    if not campaign:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail='Campaña no encontrada'
        )

    job_key = str(campaign_id)
    if job_key not in transcription_jobs:
        stats = CampaignRepository.get_campaign_stats(db, campaign_id, user.id)  # type: ignore[arg-type]
        return {
            'campaign_id': campaign_id,
            'campaign_name': campaign.campaign_name,
            'active_transcription': False,
            'stats': stats,
        }

    job = transcription_jobs[job_key]
    total: int = job['total']
    completed: int = job['completed']
    failed: int = job['failed']

    return {
        'campaign_id': campaign_id,
        'campaign_name': campaign.campaign_name,
        'active_transcription': not job['cancelled'],
        'total': total,
        'completed': completed,
        'failed': failed,
        'pending': total - completed - failed,
        'progress_percentage': round((completed / total * 100) if total > 0 else 0, 2),
        'cancelled': job['cancelled'],
    }


# ─── Análisis masivo ──────────────────────────────────────────────────────────

@router.post('/{campaign_id}/analyze-all', summary='Analizar todos los audios transcritos de la campaña')
async def analyze_all_audios(
    campaign_id: UUID,
    data: CampaignAnalysisRequest,
    user: CurrentUser,
    db: Session = Depends(get_db)
):
    campaign = CampaignRepository.get_by_id(db, campaign_id, user.id)  # type: ignore[arg-type]
    if not campaign:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail='Campaña no encontrada'
        )

    audios_with_transcription = AudioRepository.get_all_by_campaign_with_transcription(db, campaign_id)
    if not audios_with_transcription:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='No hay audios transcritos disponibles para analizar en esta campaña'
        )

    try:
        from app.services.openai_service import OpenAIService
        openai_service = OpenAIService()
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

    results = []
    total_cost = 0.0

    for audio in audios_with_transcription:
        DateTimeUtils.log(f'Analizando audio {audio.id}: {audio.audio_name}')

        result = openai_service.analyze_transcription(
            transcription=audio.transcription,  # type: ignore[arg-type]
            custom_prompt=data.prompt,
            audio_key=f'audio_{audio.id}'
        )

        if not result:
            DateTimeUtils.log(f'Error analizando audio {audio.id}', level='ERROR')
            continue

        analysis_criteria = AnalysisRepository.create_batch(
            db,
            audio_id=audio.id,  # type: ignore[arg-type]
            analysis_list=result['analysis'],
            total_in_tokens=result['in_tokens'],
            total_out_tokens=result['out_tokens'],
            total_cost=result['cost']
        )

        total_cost += result['cost']

        results.append({
            'audio_id': str(audio.id),
            'audio_name': audio.audio_name,
            'criteria_count': len(analysis_criteria),
            'cost': result['cost'],
        })

    DateTimeUtils.log(
        f'Usuario {user.id} analizó {len(results)} audios '
        f'de campaña {campaign.campaign_name} (${total_cost:.4f})'
    )

    return {
        'message': f'{len(results)} audios analizados correctamente',
        'campaign_id': campaign_id,
        'campaign_name': campaign.campaign_name,
        'analyzed_count': len(results),
        'total_cost': round(total_cost, 4),
        'results': results,
    }