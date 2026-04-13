from typing import Optional
from datetime import datetime
from pathlib import Path
from uuid import UUID
from sqlalchemy import select, func, or_
from sqlalchemy.orm import Session

from app.components.models import Audio, Campaign, AudioAnalysis
from app.components.schemas import PageMeta


class AudioRepository:
    @staticmethod
    def get_by_id(db: Session, audio_id: UUID) -> Optional[Audio]:
        return db.query(Audio).filter(Audio.id == audio_id).first()

    @staticmethod
    def get_by_user_and_id(db: Session, user_id: UUID, audio_id: UUID) -> Optional[Audio]:
        return db.query(Audio).filter(
            Audio.id == audio_id,
            Audio.campaign.has(user_id=user_id)
        ).first()

    @staticmethod
    def get_paginated(
        db: Session,
        user_id: UUID,
        *,
        page: int = 1,
        page_size: int = 10,
        campaign_id: Optional[UUID] = None,
        search: Optional[str] = None
    ) -> tuple[list[Audio], PageMeta]:
        page = max(1, page)
        page_size = max(1, min(100, page_size))

        query = db.query(Audio).join(Campaign).filter(Campaign.user_id == user_id)

        if campaign_id is not None:
            query = query.filter(Audio.campaign_id == campaign_id)

        if search:
            search_pattern = f"%{search.strip()}%"
            query = query.filter(Audio.audio_name.ilike(search_pattern))

        total = query.count()

        items = (
            query
            .order_by(Audio.register_date.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )

        pages = (total + page_size - 1) // page_size if total > 0 else 0

        meta = PageMeta(
            page=page,
            page_size=page_size,
            total=total,
            pages=pages
        )

        return items, meta

    @staticmethod
    def create(
        db: Session,
        campaign_id: UUID,
        audio_name: str,
        transcription: Optional[str] = None,
        cost: float = 0,
        minutes: float = 0
    ) -> Audio:
        audio = Audio(
            campaign_id=campaign_id,
            audio_name=audio_name,
            transcription=transcription,
            cost=cost,
            minutes=minutes
        )
        db.add(audio)
        db.commit()
        db.refresh(audio)
        return audio

    @staticmethod
    def update(db: Session, audio: Audio, **kwargs) -> Audio:
        for key, value in kwargs.items():
            if hasattr(audio, key):
                setattr(audio, key, value)
        db.commit()
        db.refresh(audio)
        return audio

    @staticmethod
    def delete(db: Session, audio: Audio) -> None:
        db.query(AudioAnalysis).filter(AudioAnalysis.audio_id == audio.id).delete(synchronize_session=False)
        db.delete(audio)
        db.commit()

    @staticmethod
    def get_total_cost(db: Session, user_id: UUID) -> float:
        result = (
            db.query(func.sum(Audio.cost))
            .join(Campaign)
            .filter(Campaign.user_id == user_id)
            .scalar()
        )
        return float(result or 0.0)

    @staticmethod
    def backfill_missing_minutes(db: Session, user_id: UUID) -> int:
        from app.services.storage_service import UploadService

        upload_dir = UploadService._upload_dir()
        audios = (
            db.query(Audio)
            .join(Campaign)
            .filter(Campaign.user_id == user_id)
            .filter(or_(Audio.minutes.is_(None), Audio.minutes <= 0))
            .all()
        )

        updated = 0
        for audio in audios:
            audio_path = upload_dir / Path(audio.audio_name).name
            if not audio_path.exists():
                continue

            try:
                duration_seconds = float(UploadService.get_duration_seconds(audio_path))
            except Exception:
                continue

            if duration_seconds <= 0:
                continue

            audio.minutes = round(duration_seconds / 60.0, 2)
            updated += 1

        if updated > 0:
            db.commit()

        return updated

    @staticmethod
    def count_by_user(db: Session, user_id: UUID) -> int:
        return (
            db.query(func.count(Audio.id))
            .join(Campaign)
            .filter(Campaign.user_id == user_id)
            .scalar()
        )

    @staticmethod
    def get_all_by_campaign(db: Session, campaign_id: UUID) -> list[Audio]:
        return db.query(Audio).filter(Audio.campaign_id == campaign_id).all()

    @staticmethod
    def get_all_by_campaign_without_transcription(db: Session, campaign_id: UUID) -> list[Audio]:
        """Devuelve audios de una campaña que aún no tienen transcripción."""
        return (
            db.query(Audio)
            .filter(Audio.campaign_id == campaign_id, Audio.transcription.is_(None))
            .all()
        )

    @staticmethod
    def get_all_by_campaign_with_transcription(db: Session, campaign_id: UUID) -> list[Audio]:
        """Devuelve audios de una campaña que ya tienen transcripción."""
        return (
            db.query(Audio)
            .filter(Audio.campaign_id == campaign_id, Audio.transcription.isnot(None))
            .all()
        )

    @staticmethod
    def get_last_updated_audio(db: Session, campaign_id: UUID, user_id: UUID) -> Optional[datetime]:
        last_audio = (
            db.query(Audio)
            .filter(Audio.campaign_id == campaign_id)
            .join(Campaign)
            .filter(Campaign.user_id == user_id)
            .order_by(Audio.updated_date.desc())
            .first()
        )

        return last_audio.updated_date if last_audio and last_audio.updated_date else None  # type: ignore


class CampaignRepository:
    @staticmethod
    def get_by_id(db: Session, campaign_id: UUID, user_id: UUID) -> Optional[Campaign]:
        return db.query(Campaign).filter(Campaign.id == campaign_id, Campaign.user_id == user_id).first()

    @staticmethod
    def get_by_name(db: Session, name: str, user_id: UUID) -> Optional[Campaign]:
        return db.query(Campaign).filter(Campaign.campaign_name == name, Campaign.user_id == user_id).first()

    @staticmethod
    def get_paginated(
        db: Session,
        user_id: UUID,
        *,
        page: int = 1,
        page_size: int = 10,
        search: Optional[str] = None
    ) -> tuple[list[Campaign], PageMeta]:
        page = max(1, page)
        page_size = max(1, min(100, page_size))

        query = db.query(Campaign).filter(Campaign.user_id == user_id)

        if search:
            search_pattern = f"%{search.strip()}%"
            query = query.filter(Campaign.campaign_name.ilike(search_pattern))

        total = query.count()

        items = (
            query
            .order_by(Campaign.register_date.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )

        pages = (total + page_size - 1) // page_size if total > 0 else 0

        meta = PageMeta(
            page=page,
            page_size=page_size,
            total=total,
            pages=pages
        )
        return items, meta

    @staticmethod
    def create(db: Session, user_id: UUID, campaign_name: str, description: Optional[str] = None) -> Campaign:
        campaign = Campaign(user_id=user_id, campaign_name=campaign_name, description=description)
        db.add(campaign)
        db.commit()
        db.refresh(campaign)
        return campaign

    @staticmethod
    def update(db: Session, campaign: Campaign, **kwargs) -> Campaign:
        for key, value in kwargs.items():
            if hasattr(campaign, key):
                setattr(campaign, key, value)
        db.commit()
        db.refresh(campaign)
        return campaign

    @staticmethod
    def delete(db: Session, campaign: Campaign) -> None:
        db.delete(campaign)
        db.commit()

    @staticmethod
    def get_campaign_stats(db: Session, campaign_id: UUID, user_id: UUID) -> dict:
        total_audios = (
            db.query(func.count(Audio.id))
            .filter(Audio.campaign_id == campaign_id)
            .scalar()
        )

        transcribed = (
            db.query(func.count(Audio.id))
            .filter(Audio.campaign_id == campaign_id, Audio.transcription.isnot(None))
            .scalar()
        )

        pending = (
            db.query(func.count(Audio.id))
            .filter(Audio.campaign_id == campaign_id, Audio.transcription.is_(None))
            .scalar()
        )

        total_cost = (
            db.query(func.sum(Audio.cost))
            .filter(Audio.campaign_id == campaign_id)
            .scalar() or 0.0
        )

        total_duration = (
            db.query(func.sum(Audio.minutes))
            .filter(Audio.campaign_id == campaign_id)
            .scalar() or 0.0
        )

        return {
            'total_audios': total_audios,
            'transcribed': transcribed,
            'pending': pending,
            'total_cost': float(total_cost),
            'total_duration_minutes': float(total_duration),
        }