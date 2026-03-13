from typing import Optional
from uuid import UUID
from sqlalchemy.orm import Session
from app.components.models import User
from app.utils.security_utils import hash_password

class UserRepository:
    
    @staticmethod
    def get_by_id(db: Session, user_id: UUID) -> Optional[User]:
        return db.query(User).filter(User.id == user_id).first()
    
    @staticmethod
    def get_by_username(db: Session, username: str) -> Optional[User]:
        return db.query(User).filter(User.username == username).first()
    
    @staticmethod
    def create(
        db: Session,
        username: str,
        password: str
    ) -> User:
        user = User(
            username=username,
            password=hash_password(password)
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    
    @staticmethod
    def update(
        db: Session,
        user_id: UUID,
        username: Optional[str] = None,
        password: Optional[str] = None
    ) -> Optional[User]:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return None
        
        if username is not None:
            user.username = username  # type: ignore
        if password is not None:
            user.password = hash_password(password)  # type: ignore
        
        db.commit()
        db.refresh(user)
        return user
    
    @staticmethod
    def delete(db: Session, user_id: UUID) -> bool:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return False
        
        db.delete(user)
        db.commit()
        return True