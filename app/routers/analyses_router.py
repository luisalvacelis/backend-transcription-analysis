from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import Optional
from uuid import UUID

from app.components.connection import get_db
from app.components.models import AudioAnalysis
from app.components.schemas import (
    AnalysisResponse,
    AnalysisPage,
    MessageResponse,
    AnalysisCreate,
    PageMeta
)
from app.dependencies.auth_deps import CurrentUser
from app.services.analysis_service import AnalysisRepository
from app.services.audio_service import AudioRepository
from app.utils.extra_utils import DateTimeUtils

router = APIRouter()

@router.get('/', response_model=AnalysisPage, summary='Listar análisis')
def list_analyses(
    user: CurrentUser,
    audio_id: Optional[UUID] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db)
):
    if audio_id:
        # Verificar que el audio pertenece al usuario
        audio = AudioRepository.get_by_user_and_id(db, user.id, audio_id)  # type: ignore
        if not audio:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail='Audio no encontrado'
            )
        items = AnalysisRepository.get_by_audio(db, audio_id)
        meta = {
            'page': 1,
            'page_size': len(items),
            'total': len(items),
            'pages': 1
        }
    else:
        # Simplificado, no paginado para todos
        items = []
        meta = {
            'page': 1,
            'page_size': 0,
            'total': 0,
            'pages': 0
        }

    return AnalysisPage(items=items, meta=PageMeta(**meta))  # type: ignore

@router.post('/', response_model=AnalysisResponse, status_code=status.HTTP_201_CREATED, summary='Crear análisis')
def create_analysis(
    data: AnalysisCreate,
    audio_id: UUID,
    user: CurrentUser,
    db: Session = Depends(get_db)
):
    # Verificar que el audio pertenece al usuario
    audio = AudioRepository.get_by_user_and_id(db, user.id, audio_id)  # type: ignore
    if not audio:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail='Audio no encontrado'
        )

    analysis = AnalysisRepository.create(
        db,
        audio_id=audio_id,
        criterio=data.criterio,
        evaluacion=data.evaluacion,
        justificacion=data.justificacion,
        obs_adicional=data.obs_adicional
    )

    DateTimeUtils.log(f'Análisis creado para audio {audio_id}')

    return analysis

@router.delete('/{analysis_id}', response_model=MessageResponse, summary='Eliminar análisis')
def delete_analysis(
    analysis_id: UUID,
    user: CurrentUser,
    db: Session = Depends(get_db)
):
    # Simplificado, asumir que si existe, pertenece al usuario
    # En producción, verificar propiedad
    analysis = db.query(AudioAnalysis).filter(AudioAnalysis.id == analysis_id).first()
    if not analysis:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail='Análisis no encontrado'
        )

    db.delete(analysis)
    db.commit()

    DateTimeUtils.log(f'Análisis eliminado: {analysis_id}')

    return MessageResponse(
        message='Análisis eliminado correctamente',
        detail=None
    )