import io
import json
import re
from datetime import datetime
from typing import Any
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from typing import Optional
from uuid import UUID
from fastapi.responses import StreamingResponse
import pandas as pd

from app.components.connection import get_db
from app.components.schemas import (
    CampaignCreate,
    CampaignUpdate,
    CampaignResponse,
    CampaignPage,
    MessageResponse,
    CampaignTranscribeRequest,
    CampaignAnalysisRequest,
    CampaignAsyncAnalysisRequest,
    CampaignPipelineRequest,
)
from app.dependencies.auth_deps import CurrentUser
from app.services.audio_service import CampaignRepository, AudioRepository
from app.services.analysis_service import AnalysisRepository
from app.services.config_service import (
    OutputFormatRepository,
    PromptTemplateRepository,
    get_default_metadata_columns_by_type,
    is_valid_metadata_extraction_type,
    DEFAULT_METADATA_EXTRACTION_TYPE,
)
from app.utils.extra_utils import DateTimeUtils

# In-memory job tracker: { campaign_id (str): { cancelled, total, completed, failed } }
transcription_jobs: dict[str, dict] = {}
analysis_jobs: dict[str, dict] = {}

router = APIRouter()


_TIMED_TRANSCRIPT_LINE = re.compile(r'^\d{2}:\d{2}\.\d{3}\s-\s\d{2}:\d{2}\.\d{3}\s\|\s[^|]+\s\|\s.+$')


def _has_timed_transcription(transcription: str | None) -> bool:
    text = (transcription or '').strip()
    if not text:
        return False
    first_line = text.splitlines()[0].strip() if text.splitlines() else ''
    return bool(_TIMED_TRANSCRIPT_LINE.match(first_line))


def _get_audios_pending_or_legacy_transcription(db: Session, campaign_id: UUID) -> list[Any]:
    audios = AudioRepository.get_all_by_campaign(db, campaign_id)
    return [audio for audio in audios if not _has_timed_transcription(getattr(audio, 'transcription', None))]


def _extract_analysis_and_layout(result_json: str | None) -> tuple[dict[str, Any], dict[str, Any]]:
    if not result_json:
        return {}, {}

    try:
        parsed = json.loads(result_json)
    except Exception:
        return {}, {}

    if isinstance(parsed, dict):
        if 'analysis' in parsed:
            analysis = parsed.get('analysis')
            layout = parsed.get('layout') if isinstance(parsed.get('layout'), dict) else {}
            if isinstance(analysis, dict):
                return analysis, layout
            if isinstance(analysis, list) and analysis and isinstance(analysis[0], dict):
                return analysis[0], layout
            return {}, layout
        return parsed, {}

    return {}, {}


def _split_text(text: str | None, chunk_size: int) -> list[str]:
    clean = (text or '').strip()
    if not clean:
        return []
    if chunk_size <= 0:
        chunk_size = 32000
    return [clean[i:i + chunk_size] for i in range(0, len(clean), chunk_size)]


def _resolve_source_value(source: Any, field_name: str, default_value: Any = '') -> Any:
    if source is None or not field_name:
        return default_value

    if isinstance(source, dict):
        value = source.get(field_name, default_value)
    else:
        value = getattr(source, field_name, default_value)

    return default_value if value is None else value


def _basename_without_extension(audio_name: str | None) -> str:
    raw = (audio_name or '').strip()
    if not raw:
        return ''
    for suffix in ('.mp3', '.wav', '.ogg', '.ogm', '.m4a'):
        if raw.lower().endswith(suffix):
            return raw[: -len(suffix)]
    return raw


def _parse_date_from_name(name: str) -> datetime | None:
    patterns = [
        r'(\d{4})[-_](\d{2})[-_](\d{2})',
        r'(\d{2})[-_](\d{2})[-_](\d{4})',
        r'(\d{2})[-_](\d{2})[-_](\d{2})',
        r'(\d{8})',
    ]
    for pattern in patterns:
        match = re.search(pattern, name)
        if not match:
            continue

        groups = match.groups()
        try:
            if len(groups) == 3 and len(groups[0]) == 4:
                return datetime(int(groups[0]), int(groups[1]), int(groups[2]))
            if len(groups) == 3 and len(groups[2]) == 4:
                return datetime(int(groups[2]), int(groups[1]), int(groups[0]))
            if len(groups) == 3 and len(groups[0]) == 2 and len(groups[2]) == 2:
                year = 2000 + int(groups[2])
                return datetime(year, int(groups[1]), int(groups[0]))
            if len(groups) == 1 and len(groups[0]) == 8:
                token = groups[0]
                return datetime(int(token[0:4]), int(token[4:6]), int(token[6:8]))
        except Exception:
            continue

    return None


def _week_of_month_roman(date_value: datetime | None) -> str:
    if not date_value:
        return ''

    week_index = ((date_value.day - 1) // 7) + 1
    roman_weeks = {
        1: 'I',
        2: 'II',
        3: 'III',
        4: 'IV',
        5: 'V',
    }
    return roman_weeks.get(week_index, 'V')


def _derive_audio_metadata(audio: Any, extraction_type: str, campaign: Any | None = None) -> dict[str, Any]:
    audio_name = _basename_without_extension(getattr(audio, 'audio_name', '') or '')
    tokens = [part for part in re.split(r'[_\s]+', audio_name) if part]
    parsed_date = _parse_date_from_name(audio_name)

    # Modelo: campos fijos + metadata derivada del audio/campana
    dni_evaluador = '00000000'
    evaluador = 'VALTX_TRANSCRIPTOR'
    fecha_llamada = parsed_date.strftime('%Y-%m-%d') if parsed_date else ''
    fecha_evaluacion = datetime.now().strftime('%Y-%m-%d')
    semana = _week_of_month_roman(parsed_date)
    periodo = parsed_date.strftime('%m') if parsed_date else ''

    ejecutivo_de_ventas = ''
    if len(tokens) >= 3:
        ejecutivo_de_ventas = tokens[2]
    elif len(tokens) >= 2:
        ejecutivo_de_ventas = tokens[1]

    campaign_name = str(getattr(campaign, 'campaign_name', '') or '').strip()
    fuvex = campaign_name

    return {
        'dni_evaluador': dni_evaluador,
        'evaluador': evaluador,
        'fecha_de_evaluacion': fecha_evaluacion,
        'semana': semana,
        'fuvex': fuvex,
        'periodo': periodo,
        'ejecutivo_de_ventas': ejecutivo_de_ventas,
        'tipo': '',
        'id_de_grabacion': audio_name,
        'fecha_llamada': fecha_llamada,
    }


def _build_observation_text(analyses: list[dict[str, Any]], start: int, end: int, include_evaluations: list[str]) -> str:
    values: list[str] = []
    allowed = {str(item).strip().lower() for item in include_evaluations if str(item).strip()}

    for index in range(start, end + 1):
        position = index - 1
        if position < 0 or position >= len(analyses):
            continue

        item = analyses[position]
        evaluation = str(item.get('evaluacion') or item.get('evaluación') or '').strip().lower()
        justification = str(item.get('justificacion') or item.get('justificación') or '').strip()
        if not justification:
            continue

        if allowed and evaluation not in allowed:
            continue

        criterion = str(item.get('criterio') or index).strip()
        values.append(f'{index}. {criterion}: {justification}')

    return '\n'.join(values)


def _build_wide_export_row(audio, analyses: list[Any], layout_template: dict[str, Any] | None = None, campaign: Any | None = None, user: Any | None = None) -> dict[str, Any]:
    parsed_items: list[dict[str, Any]] = []
    layout_config: dict[str, Any] = {}

    for item in analyses:
        analysis_data, item_layout = _extract_analysis_and_layout(item.result_json)
        parsed_items.append(analysis_data or {})
        if not layout_config and item_layout:
            layout_config = item_layout

    if not layout_config and layout_template:
        layout_config = layout_template

    row: dict[str, Any] = {
        'AUDIO_ID': str(audio.id),
        'AUDIO_NOMBRE': audio.audio_name,
        'CANTIDAD_CRITERIOS': len(parsed_items),
    }

    extraction_type = str(layout_config.get('metadata_extraction_type') or DEFAULT_METADATA_EXTRACTION_TYPE).strip()
    metadata_columns = layout_config.get('metadata_columns') or layout_config.get('fixed_columns') or []
    if (not metadata_columns) and extraction_type and extraction_type != 'none':
        metadata_columns = get_default_metadata_columns_by_type(extraction_type)

    if isinstance(metadata_columns, list):
        derived = _derive_audio_metadata(audio, extraction_type, campaign=campaign) if extraction_type and extraction_type != 'none' else {}
        source_map = {
            'audio': audio,
            'campaign': campaign,
            'user': user,
            'derived': derived,
        }
        for column_cfg in metadata_columns:
            if not isinstance(column_cfg, dict):
                continue

            column_name = str(column_cfg.get('column') or column_cfg.get('name') or '').strip()
            if not column_name:
                continue

            source_name = str(column_cfg.get('source') or 'audio').strip().lower()
            source_obj = source_map.get(source_name)
            field_name = str(column_cfg.get('field') or column_cfg.get('source_field') or '').strip()

            if 'value' in column_cfg:
                resolved_value = column_cfg.get('value')
            elif source_obj is not None and field_name:
                resolved_value = _resolve_source_value(source_obj, field_name, column_cfg.get('default', ''))
            else:
                resolved_value = column_cfg.get('default', '')

            row[column_name] = '' if resolved_value is None else resolved_value

        if derived:
            # Keep parity with model export: enforce canonical metadata columns.
            row['DNI_EVALUADOR'] = derived.get('dni_evaluador', '')
            row['EVALUADOR'] = derived.get('evaluador', '')
            row['FECHA_DE_EVALUACION'] = derived.get('fecha_de_evaluacion', '')
            row['SEMANA'] = derived.get('semana', '')
            row['FUVEX'] = derived.get('fuvex', '')
            row['PERIODO'] = derived.get('periodo', '')
            row['EJECUTIVO_DE_VENTAS'] = derived.get('ejecutivo_de_ventas', '')
            row['TIPO'] = derived.get('tipo', '')
            row['ID_DE_GRABACION'] = derived.get('id_de_grabacion', '')
            row['FECHA_LLAMADA'] = derived.get('fecha_llamada', '')

    for index, item in enumerate(parsed_items, start=1):
        row[str(index)] = item.get('evaluacion') or item.get('evaluación') or ''

    observation_groups = layout_config.get('observation_groups') or layout_config.get('ranges') or []
    if isinstance(observation_groups, list):
        for group in observation_groups:
            if not isinstance(group, dict):
                continue
            start = int(group.get('from') or group.get('start') or 0)
            end = int(group.get('to') or group.get('end') or 0)
            column = str(group.get('column') or f'observaciones_{start}_al_{end}')
            include_evaluations = group.get('include_evaluations') or ['No cumple']
            if start > 0 and end >= start:
                row[column] = _build_observation_text(parsed_items, start, end, include_evaluations)

    transcription_cfg = layout_config.get('transcription') or {}
    if not isinstance(transcription_cfg, dict):
        transcription_cfg = {}
    if transcription_cfg.get('enabled', True):
        chunk_size = int(transcription_cfg.get('chunk_size') or 32000)
        prefix = str(transcription_cfg.get('column_prefix') or 'TRANSCRIPCION_LLAMADA')
        for idx, chunk in enumerate(_split_text(getattr(audio, 'transcription', None), chunk_size), start=1):
            row[f'{prefix}_{idx}'] = chunk

    return row


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

        audios = _get_audios_pending_or_legacy_transcription(db, campaign_id)

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

    audios = _get_audios_pending_or_legacy_transcription(db, campaign_id)
    if not audios:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='No hay audios pendientes de transcripcion o sin formato TIME en esta campana'
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


def _process_campaign_analysis(
    campaign_id: UUID,
    user_id: UUID,
    prompt_text: str,
    output_fields: list[str],
    format_snapshot: dict[str, Any] | None,
) -> None:
    db = None
    job_key = str(campaign_id)
    try:
        from app.components.connection import SessionLocal
        from app.services.openai_service import OpenAIService

        db = SessionLocal()

        audios = AudioRepository.get_all_by_campaign_with_transcription(db, campaign_id)
        analysis_jobs[job_key] = {
            'cancelled': False,
            'total': len(audios),
            'completed': 0,
            'failed': 0,
            'message': 'Analisis en progreso',
        }

        service = OpenAIService()

        for audio in audios:
            if analysis_jobs[job_key]['cancelled']:
                analysis_jobs[job_key]['message'] = 'Analisis cancelado por usuario'
                break

            try:
                AnalysisRepository.delete_by_audio(db, audio.id)  # type: ignore[arg-type]
                result = service.analyze_transcription(
                    transcription=audio.transcription or '',
                    custom_prompt=prompt_text,
                    audio_key=f'audio_{audio.id}',
                    output_fields=output_fields,
                )

                AnalysisRepository.create_batch(
                    db,
                    audio_id=audio.id,  # type: ignore[arg-type]
                    analysis_list=result['analysis'],
                    total_in_tokens=result['in_tokens'],
                    total_out_tokens=result['out_tokens'],
                    total_cost=result['cost'],
                    format_snapshot=format_snapshot,
                )
                analysis_jobs[job_key]['completed'] += 1
            except Exception as e:
                DateTimeUtils.log(f'Error analizando audio {audio.id}: {e}', level='ERROR')
                analysis_jobs[job_key]['failed'] += 1

        if not analysis_jobs[job_key]['cancelled']:
            analysis_jobs[job_key]['message'] = 'Analisis finalizado'

    except Exception as e:
        DateTimeUtils.log(f'Error en analisis masivo de campana {campaign_id}: {e}', level='ERROR')
        if job_key not in analysis_jobs:
            analysis_jobs[job_key] = {
                'cancelled': False,
                'total': 0,
                'completed': 0,
                'failed': 0,
                'message': 'Error iniciando analisis',
            }
    finally:
        if db:
            db.close()


def _run_transcription_in_worker(db: Session, campaign_id: UUID, provider: str) -> dict:
    audios = _get_audios_pending_or_legacy_transcription(db, campaign_id)
    total = len(audios)
    completed = 0
    failed = 0

    for audio in audios:
        try:
            if provider == 'whisperx':
                from app.services.whisperx_service import WhisperXService
                service = WhisperXService()
                service.process_audio(audio, db)
            else:
                from app.services.deepgram_service import DeepgramService
                service = DeepgramService()
                service.process_audio(audio, db)
            completed += 1
        except Exception as e:
            DateTimeUtils.log(f'Error transcribiendo audio {audio.id}: {e}', level='ERROR')
            failed += 1

    return {'total': total, 'completed': completed, 'failed': failed}


def _process_campaign_pipeline(
    campaign_id: UUID,
    user_id: UUID,
    mode: str,
    transcribe_provider: str,
    prompt_text: str | None,
    output_fields: list[str] | None,
    format_snapshot: dict[str, Any] | None,
) -> None:
    db = None
    job_key = str(campaign_id)
    try:
        from app.components.connection import SessionLocal
        db = SessionLocal()

        analysis_jobs[job_key] = {
            'cancelled': False,
            'total': 0,
            'completed': 0,
            'failed': 0,
            'message': 'Pipeline en progreso',
        }

        if mode in ('transcribe', 'both'):
            tstats = _run_transcription_in_worker(db, campaign_id, transcribe_provider)
            analysis_jobs[job_key]['message'] = f"Transcripcion completada ({tstats['completed']}/{tstats['total']})"

        if mode in ('analyze', 'both'):
            if not prompt_text or not output_fields:
                analysis_jobs[job_key]['message'] = 'Pipeline invalido: faltan prompt/formato para analisis'
                return
            _process_campaign_analysis(campaign_id, user_id, prompt_text, output_fields, format_snapshot)

        if mode == 'transcribe':
            analysis_jobs[job_key]['message'] = 'Pipeline finalizado: solo transcripcion'

    except Exception as e:
        DateTimeUtils.log(f'Error en pipeline de campana {campaign_id}: {e}', level='ERROR')
        analysis_jobs[job_key] = {
            'cancelled': False,
            'total': 0,
            'completed': 0,
            'failed': 0,
            'message': 'Error ejecutando pipeline',
        }
    finally:
        if db:
            db.close()


@router.post('/{campaign_id}/analyze-all-async', summary='Analizar todos los audios de manera asincrona')
def analyze_all_audios_async(
    campaign_id: UUID,
    data: CampaignAsyncAnalysisRequest,
    background_tasks: BackgroundTasks,
    user: CurrentUser,
    db: Session = Depends(get_db),
):
    campaign = CampaignRepository.get_by_id(db, campaign_id, user.id)  # type: ignore[arg-type]
    if not campaign:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Campana no encontrada')

    prompt = PromptTemplateRepository.get_by_id(db, data.prompt_template_id, user.id)  # type: ignore[arg-type]
    if not prompt or not prompt.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Prompt no encontrado o inactivo')

    output_format = OutputFormatRepository.get_by_id(db, data.output_format_id, user.id)  # type: ignore[arg-type]
    if not output_format or not output_format.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Formato no encontrado o inactivo')

    audios_with_transcription = AudioRepository.get_all_by_campaign_with_transcription(db, campaign_id)
    if not audios_with_transcription:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='No hay audios transcritos para analizar',
        )

    output_fields = OutputFormatRepository.parse_fields(output_format)
    if not output_fields:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Formato de salida sin campos validos')
    format_snapshot = OutputFormatRepository.parse_layout_config(output_format)

    background_tasks.add_task(
        _process_campaign_analysis,
        campaign_id=campaign_id,
        user_id=user.id,  # type: ignore[arg-type]
        prompt_text=prompt.prompt_text,
        output_fields=output_fields,
        format_snapshot=format_snapshot,
    )

    return {
        'message': 'Analisis agregado a cola',
        'campaign_id': campaign_id,
        'campaign_name': campaign.campaign_name,
        'total_audios': len(audios_with_transcription),
    }


@router.post('/{campaign_id}/pipeline-async', summary='Ejecutar pipeline asincrono por modo')
def run_campaign_pipeline_async(
    campaign_id: UUID,
    data: CampaignPipelineRequest,
    background_tasks: BackgroundTasks,
    user: CurrentUser,
    db: Session = Depends(get_db),
):
    campaign = CampaignRepository.get_by_id(db, campaign_id, user.id)  # type: ignore[arg-type]
    if not campaign:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Campana no encontrada')

    mode = (data.mode or '').strip().lower()
    if mode not in ('transcribe', 'analyze', 'both'):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='mode debe ser transcribe, analyze o both')

    prompt_text = None
    output_fields = None
    format_snapshot = None
    metadata_extraction_type = (data.metadata_extraction_type or '').strip()
    if metadata_extraction_type and not is_valid_metadata_extraction_type(metadata_extraction_type):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='metadata_extraction_type invalido',
        )
    if mode in ('analyze', 'both'):
        if not data.prompt_template_id or not data.output_format_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='prompt_template_id y output_format_id son obligatorios para analizar')

        prompt = PromptTemplateRepository.get_by_id(db, data.prompt_template_id, user.id)  # type: ignore[arg-type]
        if not prompt or not prompt.is_active:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Prompt no encontrado o inactivo')

        output_format = OutputFormatRepository.get_by_id(db, data.output_format_id, user.id)  # type: ignore[arg-type]
        if not output_format or not output_format.is_active:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Formato no encontrado o inactivo')

        output_fields = OutputFormatRepository.parse_fields(output_format)
        if not output_fields:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Formato de salida sin campos validos')
        prompt_text = prompt.prompt_text
        format_snapshot = OutputFormatRepository.parse_layout_config(output_format)

        if metadata_extraction_type:
            format_snapshot['metadata_extraction_type'] = metadata_extraction_type

    background_tasks.add_task(
        _process_campaign_pipeline,
        campaign_id=campaign_id,
        user_id=user.id,  # type: ignore[arg-type]
        mode=mode,
        transcribe_provider=data.transcribe_provider,
        prompt_text=prompt_text,
        output_fields=output_fields,
        format_snapshot=format_snapshot,
    )

    return {
        'message': f'Pipeline iniciado en modo {mode}',
        'campaign_id': campaign_id,
        'campaign_name': campaign.campaign_name,
        'mode': mode,
        'metadata_extraction_type': metadata_extraction_type or None,
    }


@router.post('/{campaign_id}/analyze-stop', summary='Detener analisis activo de la campana')
def stop_analysis(
    campaign_id: UUID,
    user: CurrentUser,
    db: Session = Depends(get_db),
):
    campaign = CampaignRepository.get_by_id(db, campaign_id, user.id)  # type: ignore[arg-type]
    if not campaign:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Campana no encontrada')

    job_key = str(campaign_id)
    if job_key not in analysis_jobs:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='No hay analisis activo para esta campana')

    analysis_jobs[job_key]['cancelled'] = True
    analysis_jobs[job_key]['message'] = 'Cancelando analisis...'
    return {
        'message': 'Analisis detenido',
        'campaign_id': campaign_id,
        'campaign_name': campaign.campaign_name,
    }


@router.get('/{campaign_id}/analyze-status', summary='Ver progreso de analisis')
def get_analysis_status(
    campaign_id: UUID,
    user: CurrentUser,
    db: Session = Depends(get_db),
):
    campaign = CampaignRepository.get_by_id(db, campaign_id, user.id)  # type: ignore[arg-type]
    if not campaign:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Campana no encontrada')

    job_key = str(campaign_id)
    if job_key not in analysis_jobs:
        audios_with_transcription = AudioRepository.get_all_by_campaign_with_transcription(db, campaign_id)
        analyzed_count = 0
        for audio in audios_with_transcription:
            analyzed_count += len(AnalysisRepository.get_by_audio(db, audio.id)) > 0  # type: ignore[arg-type]
        total = len(audios_with_transcription)
        return {
            'campaign_id': campaign_id,
            'campaign_name': campaign.campaign_name,
            'active_analysis': False,
            'total': total,
            'completed': analyzed_count,
            'failed': 0,
            'pending': max(total - analyzed_count, 0),
            'progress_percentage': round((analyzed_count / total * 100) if total > 0 else 0, 2),
            'cancelled': False,
            'message': 'Sin analisis activo',
        }

    job = analysis_jobs[job_key]
    total = job['total']
    completed = job['completed']
    failed = job['failed']
    pending = max(total - completed - failed, 0)
    return {
        'campaign_id': campaign_id,
        'campaign_name': campaign.campaign_name,
        'active_analysis': not job['cancelled'] and pending > 0,
        'total': total,
        'completed': completed,
        'failed': failed,
        'pending': pending,
        'progress_percentage': round((completed / total * 100) if total > 0 else 0, 2),
        'cancelled': job['cancelled'],
        'message': job.get('message', ''),
    }


@router.get('/{campaign_id}/analysis-results', summary='Listar resultados de analisis por campana')
def list_campaign_analysis_results(
    campaign_id: UUID,
    user: CurrentUser,
    db: Session = Depends(get_db),
):
    campaign = CampaignRepository.get_by_id(db, campaign_id, user.id)  # type: ignore[arg-type]
    if not campaign:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Campana no encontrada')

    audios = AudioRepository.get_all_by_campaign_with_transcription(db, campaign_id)
    rows = []
    for audio in audios:
        analyses = AnalysisRepository.get_by_audio(db, audio.id)  # type: ignore[arg-type]
        for item in analyses:
            parsed_data, _layout = _extract_analysis_and_layout(item.result_json)
            rows.append({
                'audio_id': str(audio.id),
                'audio_name': audio.audio_name,
                'criterio': item.criterio,
                'evaluacion': item.evaluacion,
                'justificacion': item.justificacion,
                'obs_adicional': item.obs_adicional,
                'cost': float(item.cost or 0),
                'data': parsed_data,
            })

    return {
        'campaign_id': campaign_id,
        'campaign_name': campaign.campaign_name,
        'total_rows': len(rows),
        'items': rows,
    }


@router.get('/{campaign_id}/transcriptions', summary='Listar transcripciones de audios por campana')
def list_campaign_transcriptions(
    campaign_id: UUID,
    user: CurrentUser,
    db: Session = Depends(get_db),
):
    campaign = CampaignRepository.get_by_id(db, campaign_id, user.id)  # type: ignore[arg-type]
    if not campaign:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Campana no encontrada')

    AudioRepository.backfill_missing_minutes(db, user.id)  # type: ignore[arg-type]

    audios = AudioRepository.get_all_by_campaign(db, campaign_id)
    items = [
        {
            'audio_id': str(audio.id),
            'audio_name': audio.audio_name,
            'transcription': audio.transcription or '',
            'minutes': float(audio.minutes or 0),
        }
        for audio in audios
    ]

    return {
        'campaign_id': campaign_id,
        'campaign_name': campaign.campaign_name,
        'total_rows': len(items),
        'items': items,
    }


@router.get('/{campaign_id}/analysis-export', summary='Descargar resultados en Excel')
def export_campaign_analysis_excel(
    campaign_id: UUID,
    user: CurrentUser,
    db: Session = Depends(get_db),
):
    campaign = CampaignRepository.get_by_id(db, campaign_id, user.id)  # type: ignore[arg-type]
    if not campaign:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Campana no encontrada')

    audios = AudioRepository.get_all_by_campaign(db, campaign_id)
    audio_analyses: list[tuple[Any, list[Any], bool]] = []
    wide_layout_used = False
    layout_template: dict[str, Any] | None = None
    for audio in audios:
        analyses = AnalysisRepository.get_by_audio(db, audio.id)  # type: ignore[arg-type]
        audio_layouts = [_extract_analysis_and_layout(item.result_json)[1] for item in analyses]
        audio_has_layout = any(audio_layouts)
        wide_layout_used = wide_layout_used or audio_has_layout
        if not layout_template:
            layout_template = next((layout for layout in audio_layouts if layout), None)
        audio_analyses.append((audio, analyses, audio_has_layout))

    results_rows: list[dict] = []
    costs_rows: list[dict] = []

    for audio, analyses, _audio_has_layout in audio_analyses:
        if wide_layout_used and analyses:
            results_rows.append(_build_wide_export_row(audio, analyses, layout_template, campaign=campaign, user=user))
        else:
            for item in analyses:
                parsed_data, _layout = _extract_analysis_and_layout(item.result_json)
                results_rows.append({
                    'audio_id': str(audio.id),
                    'audio_name': audio.audio_name,
                    'analysis_cost': float(item.cost or 0),
                    **(parsed_data or {
                        'criterio': item.criterio,
                        'evaluacion': item.evaluacion,
                        'justificacion': item.justificacion,
                        'obs_adicional': item.obs_adicional,
                    }),
                })

        costs_rows.append({
            'audio_id': str(audio.id),
            'audio_name': audio.audio_name,
            'minutes': float(audio.minutes or 0),
            'transcription_cost': float(audio.cost or 0),
            'analysis_items': len(analyses),
            'analysis_total_cost': float(sum(float(a.cost or 0) for a in analyses)),
        })

    if not results_rows:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='No hay resultados de analisis para exportar')

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        pd.DataFrame(results_rows).to_excel(writer, index=False, sheet_name='resultados')
        pd.DataFrame(costs_rows).to_excel(writer, index=False, sheet_name='costos')

    output.seek(0)
    filename = f"analysis_{campaign.campaign_name.replace(' ', '_')}.xlsx"
    return StreamingResponse(
        output,
        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition': f'attachment; filename={filename}'},
    )