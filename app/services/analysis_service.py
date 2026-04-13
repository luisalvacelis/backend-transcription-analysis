import json
from typing import Optional
from uuid import UUID
from sqlalchemy.orm import Session

from app.components.models import AudioAnalysis  # pyright: ignore[reportMissingImports]
from app.utils.extra_utils import DateTimeUtils  # pyright: ignore[reportMissingImports]

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
        cost: Optional[float] = None,
        result_json: Optional[str] = None,
    ) -> AudioAnalysis:
        analysis = AudioAnalysis(
            audio_id=audio_id,
            criterio=criterio,
            evaluacion=evaluacion,
            justificacion=justificacion,
            obs_adicional=obs_adicional,
            in_token=in_token,
            out_token=out_token,
            cost=cost,
            result_json=result_json,
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
        total_cost: float,
        format_snapshot: Optional[dict] = None,
    ) -> list[AudioAnalysis]:
        num_criteria = len(analysis_list)
        in_tokens_per_criterion = total_in_tokens // num_criteria if num_criteria > 0 else 0
        out_tokens_per_criterion = total_out_tokens // num_criteria if num_criteria > 0 else 0
        cost_per_criterion = total_cost / num_criteria if num_criteria > 0 else 0.0

        results = []
        for item in analysis_list:
            payload = {'analysis': item}
            if format_snapshot is not None:
                payload['layout'] = format_snapshot
            raw_json = json.dumps(payload, ensure_ascii=True)
            criterio = str(
                item.get('criterio')
                or item.get('criterio_nombre')
                or item.get('criteria')
                or 'General'
            )
            evaluacion = str(
                item.get('evaluacion')
                or item.get('evaluación')
                or item.get('resultado')
                or item.get('estado')
                or item.get('evaluation')
                or 'No definido'
            )
            justificacion = str(
                item.get('justificacion')
                or item.get('justificación')
                or item.get('detalle')
                or item.get('justification')
                or 'Sin detalle'
            )
            analysis = AnalysisRepository.create(
                db,
                audio_id=audio_id,
                criterio=criterio,
                evaluacion=evaluacion,
                justificacion=justificacion,
                obs_adicional=item.get('obs_adicional') or item.get('observaciones') or item.get('obs'),
                in_token=in_tokens_per_criterion,
                out_token=out_tokens_per_criterion,
                cost=cost_per_criterion,
                result_json=raw_json,
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