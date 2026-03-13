from typing import Optional
from uuid import UUID
from sqlalchemy.orm import Session

from app.components.models import AudioAnalysis
from app.utils.extra_utils import DateTimeUtils

class AnalysisRepository:
    @staticmethod
    def create(
        db: Session,
        audio_id: UUID,
        criterio: str,
        evaluacion: str,
        justificacion: str,
        obs_adicional: Optional[str] = None,
        in_token: Optional[int] = None,
        out_token: Optional[int] = None,
        cost: Optional[float] = None
    ) -> AudioAnalysis:
        analysis = AudioAnalysis(
            audio_id=audio_id,
            criterio=criterio,
            evaluacion=evaluacion,
            justificacion=justificacion,
            obs_adicional=obs_adicional,
            in_token=in_token,
            out_token=out_token,
            cost=cost
        )
        db.add(analysis)
        db.commit()
        db.refresh(analysis)
        return analysis

    @staticmethod
    def create_batch(
        db: Session,
        audio_id: UUID,
        analysis_list: list[dict],
        total_in_tokens: int,
        total_out_tokens: int,
        total_cost: float
    ) -> list[AudioAnalysis]:
        num_criteria = len(analysis_list)
        in_tokens_per_criterion = total_in_tokens // num_criteria if num_criteria > 0 else 0
        out_tokens_per_criterion = total_out_tokens // num_criteria if num_criteria > 0 else 0
        cost_per_criterion = total_cost / num_criteria if num_criteria > 0 else 0.0

        results = []
        for item in analysis_list:
            analysis = AnalysisRepository.create(
                db,
                audio_id=audio_id,
                criterio=item.get('criterio', ''),
                evaluacion=item.get('evaluacion', ''),
                justificacion=item.get('justificacion', ''),
                obs_adicional=item.get('obs_adicional'),
                in_token=in_tokens_per_criterion,
                out_token=out_tokens_per_criterion,
                cost=cost_per_criterion
            )
            results.append(analysis)

        DateTimeUtils.log(f'Creados {len(results)} criterios de análisis para audio {audio_id}')

        return results

    @staticmethod
    def get_by_audio(db: Session, audio_id: UUID) -> list[AudioAnalysis]:
        return db.query(AudioAnalysis).filter(AudioAnalysis.audio_id == audio_id).all()

    @staticmethod
    def delete_by_audio(db: Session, audio_id: UUID) -> int:
        count = db.query(AudioAnalysis).filter(AudioAnalysis.audio_id == audio_id).delete()
        db.commit()
        return count