import os
from pathlib import Path
from typing import Callable
import sys

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / '.env', override=True)

class Settings:
    API_TITLE: str = os.getenv('API_TITLE', 'Transcription And Analysis App API')
    API_VERSION: str = os.getenv('API_VERSION', '1.0.0')
    
    CORS_ORIGINS: list[str] = os.getenv('CORS_ORIGINS', 'http://localhost:4200,http://localhost:3000').split(',')
    CORS_CREDENTIALS: bool = os.getenv('CORS_CREDENTIALS', 'true').lower() == 'true'

settings = Settings()

from app.routers.auth_router import router as auth_router
from app.routers.campaigns_router import router as campaigns_router
from app.routers.audios_router import router as audios_router
from app.routers.analyses_router import router as analyses_router
from fastapi import Depends
from app.dependencies.auth_deps import get_current_user

app = FastAPI(
    title=settings.API_TITLE,
    version=settings.API_VERSION,
    description='API REST para transcripción y análisis de audios',
    docs_url='/docs',
    redoc_url='/redoc',
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=settings.CORS_CREDENTIALS,
    allow_methods=['*'],
    allow_headers=['*'],
)

app.include_router(auth_router, prefix='/auth', tags=['Authentication'])
app.include_router(campaigns_router, prefix='/campaigns', tags=['Campaigns'], dependencies=[Depends(get_current_user)])
app.include_router(audios_router, prefix='/audios', tags=['Audios'], dependencies=[Depends(get_current_user)])
app.include_router(analyses_router, prefix='/analyses', tags=['Analyses'], dependencies=[Depends(get_current_user)])

@app.get('/')
def root():
    return {'message': 'API is running'}