from sqlalchemy import Column, String, Text, TIMESTAMP, func, ForeignKey, Numeric, Integer, Boolean

from sqlalchemy.dialects.postgresql import UUID

from sqlalchemy.orm import relationship

import uuid

from app.components.connection import Base

class User(Base):
    __tablename__ = 'tbl_users'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String(50), unique=True, nullable=False)
    password = Column(Text, nullable=False)
    register_date = Column(TIMESTAMP, default=func.current_timestamp())
    updated_date = Column(TIMESTAMP, onupdate=func.current_timestamp())

    campaigns = relationship("Campaign", back_populates="user")
    prompt_templates = relationship("PromptTemplate", back_populates="user")
    output_formats = relationship("OutputFormat", back_populates="user")

class Campaign(Base):
    __tablename__ = 'tbl_campaigns'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey('tbl_users.id', ondelete='CASCADE'), nullable=False)
    campaign_name = Column(String(255), nullable=False)
    description = Column(Text)
    register_date = Column(TIMESTAMP, default=func.current_timestamp())
    updated_date = Column(TIMESTAMP, onupdate=func.current_timestamp())

    user = relationship("User", back_populates="campaigns")
    audios = relationship("Audio", back_populates="campaign")

class Audio(Base):
    __tablename__ = 'tbl_audios'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    campaign_id = Column(UUID(as_uuid=True), ForeignKey('tbl_campaigns.id', ondelete='CASCADE'), nullable=False)
    audio_name = Column(String(255), nullable=False)
    transcription = Column(Text)
    cost = Column(Numeric(10,4), default=0)
    minutes = Column(Numeric(10,2), default=0)
    register_date = Column(TIMESTAMP, default=func.current_timestamp())
    updated_date = Column(TIMESTAMP, onupdate=func.current_timestamp())

    campaign = relationship("Campaign", back_populates="audios")
    analyses = relationship(
        "AudioAnalysis",
        back_populates="audio",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

class AudioAnalysis(Base):
    __tablename__ = 'tbl_audios_analysis'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    audio_id = Column(UUID(as_uuid=True), ForeignKey('tbl_audios.id', ondelete='CASCADE'), nullable=False)
    criterio = Column(Text, nullable=False)
    evaluacion = Column(String(50), nullable=False)
    justificacion = Column(Text)
    obs_adicional = Column(Text)
    register_date = Column(TIMESTAMP, default=func.current_timestamp())
    updated_date = Column(TIMESTAMP, onupdate=func.current_timestamp())
    in_token = Column(Integer)
    out_token = Column(Integer)
    cost = Column(Numeric(10,4), default=0)
    result_json = Column(Text)

    audio = relationship("Audio", back_populates="analyses")


class PromptTemplate(Base):
    __tablename__ = 'tbl_prompt_templates'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey('tbl_users.id', ondelete='CASCADE'), nullable=False)
    name = Column(String(120), nullable=False)
    prompt_text = Column(Text, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    register_date = Column(TIMESTAMP, default=func.current_timestamp())
    updated_date = Column(TIMESTAMP, onupdate=func.current_timestamp())

    user = relationship("User", back_populates="prompt_templates")


class OutputFormat(Base):
    __tablename__ = 'tbl_output_formats'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey('tbl_users.id', ondelete='CASCADE'), nullable=False)
    name = Column(String(120), nullable=False)
    fields_json = Column(Text, nullable=False)
    description = Column(Text)
    is_active = Column(Boolean, nullable=False, default=True)
    register_date = Column(TIMESTAMP, default=func.current_timestamp())
    updated_date = Column(TIMESTAMP, onupdate=func.current_timestamp())

    user = relationship("User", back_populates="output_formats")