import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from passlib.context import CryptContext
from jose import jwt, JWTError

class SecurityConfig:
    JWT_SECRET: str = os.getenv('JWT_SECRET', 'angel_chupala')
    JWT_ALGORITHM: str = os.getenv('JWT_ALGORITHM', 'HS256')
    JWT_EXPIRE_MINUTES: int = int(os.getenv('JWT_EXPIRE_MINUTES', '60'))
    
    PWD_SCHEME: str = os.getenv('PWD_SCHEME', 'bcrypt')

config = SecurityConfig()

pwd_context = CryptContext(
    schemes=['bcrypt'],
    deprecated='auto',
)

def hash_password(plain_password: str) -> str:
    if not plain_password:
        raise ValueError('La contraseña no puede estar vacía')
    
    return pwd_context.hash(plain_password.strip())

def verify_password(plain_password: str, hashed_password: str) -> bool:
    if not plain_password or not hashed_password:
        return False
    
    try:
        return pwd_context.verify(plain_password.strip(), hashed_password)
    except Exception:
        return False

def create_access_token(subject: str, *, expires_delta: Optional[timedelta] = None, extra_claims: Optional[dict] = None) -> str:
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=config.JWT_EXPIRE_MINUTES)
    
    payload = {
        'sub': subject,
        'exp': expire,
        'iat': datetime.now(timezone.utc),
    }
    
    if extra_claims:
        payload.update(extra_claims)
    
    return jwt.encode(payload, config.JWT_SECRET, algorithm=config.JWT_ALGORITHM)

def decode_access_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, config.JWT_SECRET, algorithms=[config.JWT_ALGORITHM])
        return payload
    except JWTError:
        return None