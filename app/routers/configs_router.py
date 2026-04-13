from uuid import UUID
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.components.connection import get_db
from app.components.schemas import (
    MessageResponse,
    OutputFormatCreate,
    OutputFormatResponse,
    PromptFormatSuggestionItem,
    OutputFormatUpdate,
    PromptTemplateCreate,
    PromptTemplateResponse,
    PromptTemplateUpdate,
    MetadataExtractionTypeResponse,
)
from app.dependencies.auth_deps import CurrentUser
from app.services.config_service import (
    OutputFormatRepository,
    PromptTemplateRepository,
    suggest_prompt_format_mappings,
    list_metadata_extraction_types,
    is_valid_metadata_extraction_type,
    DEFAULT_METADATA_EXTRACTION_TYPE,
)

router = APIRouter()


def _normalize_layout_config(layout_config: dict[str, Any] | None) -> dict[str, Any] | None:
    if layout_config is None:
        return {'metadata_extraction_type': DEFAULT_METADATA_EXTRACTION_TYPE}

    extraction_type = layout_config.get('metadata_extraction_type')
    extraction_type = str(extraction_type).strip() if extraction_type is not None else ''
    if not extraction_type:
        layout_config['metadata_extraction_type'] = DEFAULT_METADATA_EXTRACTION_TYPE
        return layout_config

    if not is_valid_metadata_extraction_type(extraction_type):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='metadata_extraction_type invalido',
        )

    layout_config['metadata_extraction_type'] = extraction_type

    return layout_config


@router.get('/prompts', response_model=list[PromptTemplateResponse], summary='Listar prompts')
def list_prompts(user: CurrentUser, db: Session = Depends(get_db)):
    return PromptTemplateRepository.list_by_user(db, user.id)  # type: ignore[arg-type]


@router.post('/prompts', response_model=PromptTemplateResponse, status_code=status.HTTP_201_CREATED, summary='Crear prompt')
def create_prompt(data: PromptTemplateCreate, user: CurrentUser, db: Session = Depends(get_db)):
    return PromptTemplateRepository.create(
        db,
        user_id=user.id,  # type: ignore[arg-type]
        name=data.name,
        prompt_text=data.prompt_text,
    )


@router.put('/prompts/{prompt_id}', response_model=PromptTemplateResponse, summary='Actualizar prompt')
def update_prompt(prompt_id: UUID, data: PromptTemplateUpdate, user: CurrentUser, db: Session = Depends(get_db)):
    prompt = PromptTemplateRepository.get_by_id(db, prompt_id, user.id)  # type: ignore[arg-type]
    if not prompt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Prompt no encontrado')

    update_data = data.model_dump(exclude_unset=True)
    try:
        return PromptTemplateRepository.update(db, prompt, **update_data)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.delete('/prompts/{prompt_id}', response_model=MessageResponse, summary='Eliminar prompt')
def delete_prompt(prompt_id: UUID, user: CurrentUser, db: Session = Depends(get_db)):
    prompt = PromptTemplateRepository.get_by_id(db, prompt_id, user.id)  # type: ignore[arg-type]
    if not prompt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Prompt no encontrado')

    try:
        PromptTemplateRepository.delete(db, prompt)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return MessageResponse(message='Prompt eliminado correctamente', detail=None)


@router.get('/formats', response_model=list[OutputFormatResponse], summary='Listar formatos de salida')
def list_formats(user: CurrentUser, db: Session = Depends(get_db)):
    return OutputFormatRepository.list_by_user(db, user.id)  # type: ignore[arg-type]


@router.get('/prompt-format-suggestions', response_model=list[PromptFormatSuggestionItem], summary='Sugerir formato por prompt')
def list_prompt_format_suggestions(user: CurrentUser, db: Session = Depends(get_db)):
    return suggest_prompt_format_mappings(db, user.id)  # type: ignore[arg-type]


@router.get('/metadata-extraction-types', response_model=list[MetadataExtractionTypeResponse], summary='Listar tipos de extraccion de metadatos')
def get_metadata_extraction_types():
    return list_metadata_extraction_types()


@router.post('/formats', response_model=OutputFormatResponse, status_code=status.HTTP_201_CREATED, summary='Crear formato de salida')
def create_format(data: OutputFormatCreate, user: CurrentUser, db: Session = Depends(get_db)):
    layout_config = _normalize_layout_config(data.layout_config)
    return OutputFormatRepository.create(
        db,
        user_id=user.id,  # type: ignore[arg-type]
        name=data.name,
        fields=data.fields,
        description=data.description,
        layout_config=layout_config,
    )


@router.put('/formats/{format_id}', response_model=OutputFormatResponse, summary='Actualizar formato de salida')
def update_format(format_id: UUID, data: OutputFormatUpdate, user: CurrentUser, db: Session = Depends(get_db)):
    output_format = OutputFormatRepository.get_by_id(db, format_id, user.id)  # type: ignore[arg-type]
    if not output_format:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Formato no encontrado')

    update_data = data.model_dump(exclude_unset=True)
    if 'layout_config' in update_data:
        update_data['layout_config'] = _normalize_layout_config(update_data.get('layout_config'))
    return OutputFormatRepository.update(db, output_format, **update_data)


@router.delete('/formats/{format_id}', response_model=MessageResponse, summary='Eliminar formato de salida')
def delete_format(format_id: UUID, user: CurrentUser, db: Session = Depends(get_db)):
    output_format = OutputFormatRepository.get_by_id(db, format_id, user.id)  # type: ignore[arg-type]
    if not output_format:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Formato no encontrado')

    OutputFormatRepository.delete(db, output_format)
    return MessageResponse(message='Formato eliminado correctamente', detail=None)
