from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.components.connection import get_db
from app.components.models import User
from app.components.schemas import (
    RegisterRequest,
    LoginRequest,
    TokenResponse,
    UserResponse,
    UpdateUserRequest
)
from app.dependencies.auth_deps import get_current_user, CurrentUser
from app.services.user_service import UserRepository
from app.utils.security_utils import verify_password, create_access_token
from app.utils.extra_utils import DateTimeUtils

router = APIRouter()

@router.post(
    '/register',
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary='Registrar nuevo usuario'
)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    existing_user = db.query(User).filter(User.username == payload.username).first()
    
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail='El nombre de usuario ya está registrado'
        )
    
    try:
        user = UserRepository.create(db, payload.username, payload.password)
        
        DateTimeUtils.log(f'Usuario registrado: {user.username}')
        return user
    except Exception as e:
        DateTimeUtils.log(f'Error en registro: {e}', level='ERROR')
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Error al crear usuario'
        )

@router.post(
    '/login',
    response_model=TokenResponse,
    summary='Iniciar sesión'
)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = UserRepository.get_by_username(db, payload.username)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail='Credenciales inválidas',
            headers={'WWW-Authenticate': 'Bearer'}
        )
    
    if not verify_password(payload.password, user.password):  # type: ignore
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail='Credenciales inválidas',
            headers={'WWW-Authenticate': 'Bearer'}
        )
    
    token = create_access_token(subject=str(user.id))
    
    DateTimeUtils.log(f'Usuario autenticado: {user.username}')
    return TokenResponse(access_token=token, token_type='bearer')

@router.get(
    '/me',
    response_model=UserResponse,
    summary='Obtener perfil actual'
)
def get_me(current_user: CurrentUser):
    return current_user

@router.put(
    '/me',
    response_model=UserResponse,
    summary='Actualizar perfil actual'
)
def update_me(payload: UpdateUserRequest, current_user: CurrentUser, db: Session = Depends(get_db)):
    try:
        updated_user = UserRepository.update(
            db,
            current_user.id,  # type: ignore
            username=payload.username,
            password=payload.password
        )
        if not updated_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail='Usuario no encontrado'
            )
        
        DateTimeUtils.log(f'Usuario actualizado: {updated_user.username}')
        return updated_user
    except Exception as e:
        DateTimeUtils.log(f'Error en actualización: {e}', level='ERROR')
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Error al actualizar usuario'
        )

@router.delete(
    '/me',
    status_code=status.HTTP_204_NO_CONTENT,
    summary='Eliminar cuenta actual'
)
def delete_me(current_user: CurrentUser, db: Session = Depends(get_db)):
    try:
        success = UserRepository.delete(db, current_user.id)  # type: ignore
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail='Usuario no encontrado'
            )
        
        DateTimeUtils.log(f'Usuario eliminado: {current_user.username}')
        return None
    except Exception as e:
        DateTimeUtils.log(f'Error en eliminación: {e}', level='ERROR')
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Error al eliminar usuario'
        )