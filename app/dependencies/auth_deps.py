from typing import Annotated
import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.components.connection import get_db
from app.components.models import User
from app.utils.security_utils import decode_access_token

bearer_scheme = HTTPBearer(
    auto_error=True,
    scheme_name='Bearer Token',
    description='JWT Bearer token'
)

def get_token_payload(credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme)) -> dict:
    token = credentials.credentials
    payload = decode_access_token(token)
    
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail='Token inválido o expirado',
            headers={'WWW-Authenticate': 'Bearer'},
        )
    
    return payload

def get_current_user(payload: dict = Depends(get_token_payload), db: Session = Depends(get_db)) -> User:
    user_id_str = payload.get('sub')
    
    if not user_id_str:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail='Token inválido: falta subject',
            headers={'WWW-Authenticate': 'Bearer'},
        )
    
    try:
        user_id = uuid.UUID(user_id_str)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail='Token inválido: subject debe ser un UUID válido',
            headers={'WWW-Authenticate': 'Bearer'},
        )
    
    user = db.query(User).filter(User.id == user_id).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail='Usuario no encontrado',
            headers={'WWW-Authenticate': 'Bearer'},
        )
    
    return user

CurrentUser = Annotated[User, Depends(get_current_user)]