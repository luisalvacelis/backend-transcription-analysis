import json
import re
from typing import Any, Optional
from uuid import UUID
from sqlalchemy.orm import Session

from app.components.models import PromptTemplate, OutputFormat


PROTECTED_PROMPT_KEYWORDS = ('vector store', 'vector_store', 'scotiabank')
DEFAULT_METADATA_EXTRACTION_TYPE = 'model_default'


METADATA_EXTRACTION_TYPES: dict[str, dict[str, str]] = {
    'model_default': {
        'id': 'model_default',
        'name': 'Default del sistema (modelo)',
        'description': 'Aplica extraccion base del sistema cuando no se selecciona un tipo.',
    },
    'none': {
        'id': 'none',
        'name': 'Sin extraccion automatica',
        'description': 'No aplica parsing especial de metadatos desde el nombre del audio.',
    },
    'prompt_type_4': {
        'id': 'prompt_type_4',
        'name': 'Prompt Type 4',
        'description': 'Extrae fecha, evaluador y FUVEX desde patron de nombre tipo 4.',
    },
    'prompt_type_6': {
        'id': 'prompt_type_6',
        'name': 'Prompt Type 6',
        'description': 'Extrae fecha, evaluador y FUVEX desde patron de nombre tipo 6.',
    },
    'prompt_type_7': {
        'id': 'prompt_type_7',
        'name': 'Prompt Type 7',
        'description': 'Extrae fecha, semana y DNI evaluador desde patron de nombre tipo 7.',
    },
}


DEFAULT_METADATA_COLUMNS_BY_TYPE: dict[str, list[dict[str, str]]] = {
    'model_default': [
        {'column': 'DNI_EVALUADOR', 'source': 'derived', 'field': 'dni_evaluador'},
        {'column': 'EVALUADOR', 'source': 'derived', 'field': 'evaluador'},
        {'column': 'FECHA_DE_EVALUACION', 'source': 'derived', 'field': 'fecha_de_evaluacion'},
        {'column': 'SEMANA', 'source': 'derived', 'field': 'semana'},
        {'column': 'FUVEX', 'source': 'derived', 'field': 'fuvex'},
        {'column': 'PERIODO', 'source': 'derived', 'field': 'periodo'},
        {'column': 'EJECUTIVO_DE_VENTAS', 'source': 'derived', 'field': 'ejecutivo_de_ventas'},
        {'column': 'TIPO', 'source': 'derived', 'field': 'tipo'},
        {'column': 'ID_DE_GRABACION', 'source': 'derived', 'field': 'id_de_grabacion'},
        {'column': 'FECHA_LLAMADA', 'source': 'derived', 'field': 'fecha_llamada'},
    ],
    'prompt_type_4': [
        {'column': 'DNI_EVALUADOR', 'source': 'derived', 'field': 'dni_evaluador'},
        {'column': 'EVALUADOR', 'source': 'derived', 'field': 'evaluador'},
        {'column': 'FECHA_DE_EVALUACION', 'source': 'derived', 'field': 'fecha_de_evaluacion'},
        {'column': 'SEMANA', 'source': 'derived', 'field': 'semana'},
        {'column': 'FUVEX', 'source': 'derived', 'field': 'fuvex'},
        {'column': 'PERIODO', 'source': 'derived', 'field': 'periodo'},
        {'column': 'EJECUTIVO_DE_VENTAS', 'source': 'derived', 'field': 'ejecutivo_de_ventas'},
        {'column': 'TIPO', 'source': 'derived', 'field': 'tipo'},
        {'column': 'ID_DE_GRABACION', 'source': 'derived', 'field': 'id_de_grabacion'},
        {'column': 'FECHA_LLAMADA', 'source': 'derived', 'field': 'fecha_llamada'},
    ],
    'prompt_type_6': [
        {'column': 'DNI_EVALUADOR', 'source': 'derived', 'field': 'dni_evaluador'},
        {'column': 'EVALUADOR', 'source': 'derived', 'field': 'evaluador'},
        {'column': 'FECHA_DE_EVALUACION', 'source': 'derived', 'field': 'fecha_de_evaluacion'},
        {'column': 'SEMANA', 'source': 'derived', 'field': 'semana'},
        {'column': 'FUVEX', 'source': 'derived', 'field': 'fuvex'},
        {'column': 'PERIODO', 'source': 'derived', 'field': 'periodo'},
        {'column': 'EJECUTIVO_DE_VENTAS', 'source': 'derived', 'field': 'ejecutivo_de_ventas'},
        {'column': 'TIPO', 'source': 'derived', 'field': 'tipo'},
        {'column': 'ID_DE_GRABACION', 'source': 'derived', 'field': 'id_de_grabacion'},
        {'column': 'FECHA_LLAMADA', 'source': 'derived', 'field': 'fecha_llamada'},
    ],
    'prompt_type_7': [
        {'column': 'DNI_EVALUADOR', 'source': 'derived', 'field': 'dni_evaluador'},
        {'column': 'EVALUADOR', 'source': 'derived', 'field': 'evaluador'},
        {'column': 'FECHA_DE_EVALUACION', 'source': 'derived', 'field': 'fecha_de_evaluacion'},
        {'column': 'SEMANA', 'source': 'derived', 'field': 'semana'},
        {'column': 'FUVEX', 'source': 'derived', 'field': 'fuvex'},
        {'column': 'PERIODO', 'source': 'derived', 'field': 'periodo'},
        {'column': 'EJECUTIVO_DE_VENTAS', 'source': 'derived', 'field': 'ejecutivo_de_ventas'},
        {'column': 'TIPO', 'source': 'derived', 'field': 'tipo'},
        {'column': 'ID_DE_GRABACION', 'source': 'derived', 'field': 'id_de_grabacion'},
        {'column': 'FECHA_LLAMADA', 'source': 'derived', 'field': 'fecha_llamada'},
    ],
}


def list_metadata_extraction_types() -> list[dict[str, str]]:
    return [value for value in METADATA_EXTRACTION_TYPES.values()]


def is_valid_metadata_extraction_type(extraction_type: str | None) -> bool:
    if extraction_type is None or extraction_type == '':
        return True
    return extraction_type in METADATA_EXTRACTION_TYPES


def get_default_metadata_columns_by_type(extraction_type: str | None) -> list[dict[str, str]]:
    if not extraction_type:
        return []
    return DEFAULT_METADATA_COLUMNS_BY_TYPE.get(extraction_type, [])


def is_protected_prompt_name(name: str) -> bool:
    low = (name or '').strip().lower()
    return any(keyword in low for keyword in PROTECTED_PROMPT_KEYWORDS)


class PromptTemplateRepository:
    @staticmethod
    def list_by_user(db: Session, user_id: UUID) -> list[PromptTemplate]:
        return (
            db.query(PromptTemplate)
            .filter(PromptTemplate.user_id == user_id)
            .order_by(PromptTemplate.register_date.desc())
            .all()
        )

    @staticmethod
    def get_by_id(db: Session, prompt_id: UUID, user_id: UUID) -> Optional[PromptTemplate]:
        return (
            db.query(PromptTemplate)
            .filter(PromptTemplate.id == prompt_id, PromptTemplate.user_id == user_id)
            .first()
        )

    @staticmethod
    def create(db: Session, user_id: UUID, name: str, prompt_text: str) -> PromptTemplate:
        prompt = PromptTemplate(
            user_id=user_id,
            name=name,
            prompt_text=prompt_text,
            is_active=True,
        )
        db.add(prompt)
        db.commit()
        db.refresh(prompt)
        return prompt

    @staticmethod
    def update(db: Session, prompt: PromptTemplate, **kwargs) -> PromptTemplate:
        if is_protected_prompt_name(prompt.name):
            raise ValueError('Este prompt esta protegido y no puede modificarse')

        for key, value in kwargs.items():
            if hasattr(prompt, key) and value is not None:
                setattr(prompt, key, value)
        db.commit()
        db.refresh(prompt)
        return prompt

    @staticmethod
    def delete(db: Session, prompt: PromptTemplate) -> None:
        if is_protected_prompt_name(prompt.name):
            raise ValueError('Este prompt esta protegido y no puede eliminarse')

        db.delete(prompt)
        db.commit()


class OutputFormatRepository:
    @staticmethod
    def _parse_fields_json(fields_json: str) -> dict[str, Any] | list[Any] | Any:
        try:
            return json.loads(fields_json)
        except Exception:
            return []

    @staticmethod
    def list_by_user(db: Session, user_id: UUID) -> list[OutputFormat]:
        return (
            db.query(OutputFormat)
            .filter(OutputFormat.user_id == user_id)
            .order_by(OutputFormat.register_date.desc())
            .all()
        )

    @staticmethod
    def get_by_id(db: Session, format_id: UUID, user_id: UUID) -> Optional[OutputFormat]:
        return (
            db.query(OutputFormat)
            .filter(OutputFormat.id == format_id, OutputFormat.user_id == user_id)
            .first()
        )

    @staticmethod
    def create(
        db: Session,
        user_id: UUID,
        name: str,
        fields: list[str],
        description: Optional[str],
        layout_config: Optional[dict[str, Any]] = None,
    ) -> OutputFormat:
        payload: dict[str, Any] = {'fields': fields}
        if layout_config is not None:
            payload['layout'] = layout_config

        output = OutputFormat(
            user_id=user_id,
            name=name,
            fields_json=json.dumps(payload, ensure_ascii=True),
            description=description,
            is_active=True,
        )
        db.add(output)
        db.commit()
        db.refresh(output)
        return output

    @staticmethod
    def update(db: Session, output_format: OutputFormat, **kwargs) -> OutputFormat:
        fields = kwargs.pop('fields', None)
        if fields is not None:
            try:
                current_payload = json.loads(output_format.fields_json)
                if not isinstance(current_payload, dict):
                    current_payload = {'fields': fields}
            except Exception:
                current_payload = {'fields': fields}

            current_payload['fields'] = fields
            if 'layout_config' in kwargs:
                layout_config = kwargs.pop('layout_config')
                if layout_config is not None:
                    current_payload['layout'] = layout_config
            output_format.fields_json = json.dumps(current_payload, ensure_ascii=True)
        elif 'layout_config' in kwargs:
            layout_config = kwargs.pop('layout_config')
            try:
                current_payload = json.loads(output_format.fields_json)
                if not isinstance(current_payload, dict):
                    current_payload = {'fields': OutputFormatRepository.parse_fields(output_format)}
            except Exception:
                current_payload = {'fields': OutputFormatRepository.parse_fields(output_format)}
            if layout_config is not None:
                current_payload['layout'] = layout_config
            output_format.fields_json = json.dumps(current_payload, ensure_ascii=True)

        for key, value in kwargs.items():
            if hasattr(output_format, key) and value is not None:
                setattr(output_format, key, value)

        db.commit()
        db.refresh(output_format)
        return output_format

    @staticmethod
    def delete(db: Session, output_format: OutputFormat) -> None:
        db.delete(output_format)
        db.commit()

    @staticmethod
    def parse_fields(output_format: OutputFormat) -> list[str]:
        try:
            parsed = json.loads(output_format.fields_json)
            if isinstance(parsed, list):
                return [str(v).strip() for v in parsed if str(v).strip()]
            if isinstance(parsed, dict):
                fields = parsed.get('fields') or []
                if isinstance(fields, list):
                    return [str(v).strip() for v in fields if str(v).strip()]
        except Exception:
            pass
        return []

    @staticmethod
    def parse_layout_config(output_format: OutputFormat) -> dict[str, Any]:
        try:
            parsed = json.loads(output_format.fields_json)
            if isinstance(parsed, dict):
                layout = parsed.get('layout')
                if isinstance(layout, dict):
                    return layout
        except Exception:
            pass
        return {}


STOP_WORDS = {
    'de', 'del', 'la', 'el', 'los', 'las', 'y', 'o', 'en', 'por', 'para', 'con', 'sin',
    'analisis', 'analisis', 'prompt', 'formato', 'salida', 'template',
}


def _tokenize(text: str) -> set[str]:
    clean = re.sub(r'[^a-zA-Z0-9_ ]+', ' ', (text or '').lower())
    tokens = {token for token in clean.replace('_', ' ').split() if len(token) > 2}
    return {token for token in tokens if token not in STOP_WORDS}


def suggest_prompt_format_mappings(db: Session, user_id: UUID) -> list[dict[str, object]]:
    prompts = PromptTemplateRepository.list_by_user(db, user_id)
    formats = OutputFormatRepository.list_by_user(db, user_id)

    format_rows: list[tuple[OutputFormat, set[str]]] = []
    for output_format in formats:
        format_tokens = _tokenize(output_format.name)
        format_tokens.update(_tokenize(' '.join(OutputFormatRepository.parse_fields(output_format))))
        format_rows.append((output_format, format_tokens))

    results: list[dict[str, object]] = []
    for prompt in prompts:
        prompt_tokens = _tokenize(prompt.name)
        if not prompt_tokens:
            results.append(
                {
                    'prompt_id': prompt.id,
                    'prompt_name': prompt.name,
                    'format_id': None,
                    'format_name': None,
                    'score': 0.0,
                    'reason': 'Prompt sin tokens para sugerencia',
                }
            )
            continue

        best_format: Optional[OutputFormat] = None
        best_score = 0.0
        for output_format, format_tokens in format_rows:
            if not format_tokens:
                continue

            intersection = len(prompt_tokens.intersection(format_tokens))
            union = len(prompt_tokens.union(format_tokens))
            score = (intersection / union) if union else 0.0

            if score > best_score:
                best_score = score
                best_format = output_format

        if best_format and best_score > 0:
            results.append(
                {
                    'prompt_id': prompt.id,
                    'prompt_name': prompt.name,
                    'format_id': best_format.id,
                    'format_name': best_format.name,
                    'score': round(best_score, 3),
                    'reason': 'Coincidencia por nombre de prompt y campos del formato',
                }
            )
        else:
            results.append(
                {
                    'prompt_id': prompt.id,
                    'prompt_name': prompt.name,
                    'format_id': None,
                    'format_name': None,
                    'score': 0.0,
                    'reason': 'Sin coincidencia clara; seleccion manual recomendada',
                }
            )

    return results
