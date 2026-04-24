from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field, ConfigDict

class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=50, description='Nombre de usuario único')
    password: str = Field(..., min_length=6, max_length=200, description='Contraseña (mínimo 6 caracteres)')

class LoginRequest(BaseModel):
    username: str = Field(..., description='Nombre de usuario')
    password: str = Field(..., min_length=6, max_length=200, description='Contraseña del usuario')

class TokenResponse(BaseModel):
    access_token: str = Field(..., description='Token JWT de acceso')
    token_type: str = Field(default='bearer', description='Tipo de token')

class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    username: str
    register_date: datetime
    updated_date: Optional[datetime] = None

class UpdateUserRequest(BaseModel):
    username: Optional[str] = Field(None, min_length=1, max_length=50)
    password: Optional[str] = Field(None, min_length=6, max_length=200)

class CampaignCreate(BaseModel):
    campaign_name: str = Field(..., min_length=1, max_length=255, description='Nombre único de la campaña')
    description: Optional[str] = Field(None, description='Descripción opcional de la campaña')

class CampaignUpdate(BaseModel):
    campaign_name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None

class CampaignResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    campaign_name: str
    description: Optional[str] = None
    register_date: datetime
    updated_date: Optional[datetime] = None

class AudioResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    campaign_id: UUID
    audio_name: str
    transcription: Optional[str] = None
    cost: Optional[float] = None
    minutes: Optional[float] = None
    register_date: datetime
    updated_date: Optional[datetime] = None

class AudioWithCampaign(AudioResponse):
    campaign: CampaignResponse


class AudioUpdateRequest(BaseModel):
    audio_name: Optional[str] = Field(None, min_length=1, max_length=255)

class AnalysisCreate(BaseModel):
    criterio: str = Field(..., description='Criterio evaluado')
    evaluacion: str = Field(..., description='Evaluación del criterio')
    justificacion: str = Field(..., description='Justificación de la evaluación')
    obs_adicional: Optional[str] = Field(None, description='Observaciones adicionales')

class AnalysisResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    audio_id: UUID
    criterio: str
    evaluacion: str
    justificacion: str
    obs_adicional: Optional[str] = None
    register_date: datetime
    updated_date: Optional[datetime] = None
    in_token: Optional[int] = None
    out_token: Optional[int] = None
    cost: Optional[float] = None

class PageMeta(BaseModel):
    page: int = Field(..., ge=1, description='Página actual')
    page_size: int = Field(..., ge=1, le=100, description='Elementos por página')
    total: int = Field(..., ge=0, description='Total de elementos')
    pages: int = Field(..., ge=0, description='Total de páginas')

class AudioPage(BaseModel):
    items: list[AudioResponse]
    meta: PageMeta

class CampaignPage(BaseModel):
    items: list[CampaignResponse]
    meta: PageMeta

class AnalysisPage(BaseModel):
    items: list[AnalysisResponse]
    meta: PageMeta

class MessageResponse(BaseModel):
    message: str = Field(..., description='Mensaje de respuesta')
    detail: Optional[str] = Field(None, description='Detalle adicional')

class CampaignTranscribeRequest(BaseModel):
    provider: str = Field('deepgram', description='Proveedor: deepgram o whisperx')

class CampaignAnalysisRequest(BaseModel):
    prompt: str = Field(..., min_length=10, description='Prompt personalizado para el análisis')


class PromptTemplateCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=120)
    prompt_text: str = Field(..., min_length=10)


class PromptTemplateUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=120)
    prompt_text: Optional[str] = Field(None, min_length=10)
    is_active: Optional[bool] = None


class PromptTemplateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    name: str
    prompt_text: str
    is_active: bool
    register_date: datetime
    updated_date: Optional[datetime] = None


class OutputFormatCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=120)
    fields: list[str] = Field(..., min_length=1, description='Lista ordenada de campos de salida')
    description: Optional[str] = None
    layout_config: Optional[dict[str, Any]] = None


class OutputFormatUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=120)
    fields: Optional[list[str]] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None
    layout_config: Optional[dict[str, Any]] = None


class OutputFormatResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    name: str
    fields_json: str
    description: Optional[str] = None
    is_active: bool
    register_date: datetime
    updated_date: Optional[datetime] = None


class CampaignAsyncAnalysisRequest(BaseModel):
    prompt_template_id: UUID
    output_format_id: UUID
    provider: str = Field('openai', description='Proveedor de análisis')


class CampaignPipelineRequest(BaseModel):
    mode: str = Field(..., description='Modo: transcribe | analyze | both')
    transcribe_provider: str = Field('deepgram', description='Proveedor de transcripcion')
    analysis_provider: str = Field('openai', description='Proveedor de analisis')
    prompt_template_id: Optional[UUID] = None
    output_format_id: Optional[UUID] = None
    metadata_extraction_type: Optional[str] = None


class CampaignAsyncAnalysisStatus(BaseModel):
    campaign_id: UUID
    active_analysis: bool
    total: int
    completed: int
    failed: int
    pending: int
    progress_percentage: float
    cancelled: bool
    message: Optional[str] = None


class CampaignAnalysisResultItem(BaseModel):
    audio_id: UUID
    audio_name: str
    criterio: str
    evaluacion: str
    justificacion: str
    obs_adicional: Optional[str] = None
    cost: Optional[float] = None


class PromptFormatSuggestionItem(BaseModel):
    prompt_id: UUID
    prompt_name: str
    format_id: Optional[UUID] = None
    format_name: Optional[str] = None
    score: float = 0
    reason: str = ''


class MetadataExtractionTypeResponse(BaseModel):
    id: str
    name: str
    description: str