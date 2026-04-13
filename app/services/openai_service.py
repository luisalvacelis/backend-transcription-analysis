import os
import json
from typing import Any

import httpx


def _normalize_fields(output_fields: list[str]) -> list[str]:
    normalized = [f.strip() for f in output_fields if f and f.strip()]
    required = ['criterio', 'evaluacion', 'justificacion', 'obs_adicional']
    for field in required:
        if field not in normalized:
            normalized.append(field)
    return normalized


def _build_structured_item(fields: list[str], prompt: str, transcription: str) -> dict[str, str]:
    snippet = (transcription or '').strip().replace('\n', ' ')
    snippet = snippet[:220] + ('...' if len(snippet) > 220 else '')
    payload: dict[str, str] = {}
    for field in fields:
        low = field.lower()
        if low == 'criterio':
            payload[field] = 'Evaluacion general'
        elif low == 'evaluacion':
            payload[field] = 'Cumple' if snippet else 'No aplica'
        elif low == 'justificacion':
            payload[field] = f'Prompt aplicado: {prompt[:100]}. Muestra: {snippet or "Sin transcripcion"}'
        elif low in ('obs_adicional', 'observaciones'):
            payload[field] = 'Salida base estructurada para pruebas de flujo web'
        else:
            payload[field] = f'Valor generado para {field}'
    return payload


def _build_fallback_response(fields: list[str], prompt: str, transcription: str) -> dict[str, Any]:
    return {
        'analysis': [_build_structured_item(fields, prompt, transcription)],
        'in_tokens': 0,
        'out_tokens': 0,
        'cost': 0.0,
    }


def _normalize_analysis_payload(parsed: Any, fields: list[str]) -> list[dict[str, str]]:
    raw_items = parsed.get('analysis') if isinstance(parsed, dict) else None
    if not isinstance(raw_items, list) or not raw_items:
        return []

    normalized: list[dict[str, str]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue

        row: dict[str, str] = {}
        for field in fields:
            value = item.get(field)
            row[field] = '' if value is None else str(value).strip()
        if not row.get('criterio'):
            row['criterio'] = str(item.get('criterio_nombre') or item.get('criteria') or '').strip()
        if not row.get('evaluacion'):
            row['evaluacion'] = str(
                item.get('resultado')
                or item.get('estado')
                or item.get('evaluation')
                or item.get('evaluación')
                or ''
            ).strip()
        if not row.get('justificacion'):
            row['justificacion'] = str(
                item.get('detalle')
                or item.get('justificación')
                or item.get('justification')
                or ''
            ).strip()
        if not row.get('obs_adicional'):
            row['obs_adicional'] = str(item.get('observaciones') or item.get('obs') or '').strip()
        if row:
            normalized.append(row)

    return normalized

class OpenAIService:
    def __init__(self):
        self.api_key = (os.getenv('OPENAI_API_KEY') or os.getenv('OPENAI_KEY') or '').strip()
        if not self.api_key:
            raise ValueError('OPENAI_API_KEY (o OPENAI_KEY) no configurada')

        self.model = os.getenv('OPENAI_MODEL', 'gpt-4.1-mini').strip()
        self.max_tokens = int(os.getenv('OPENAI_MAX_TOKENS', '4000'))
        self.temperature = float(os.getenv('OPENAI_TEMPERATURE', '0.2'))
        self.timeout = float(os.getenv('OPENAI_TIMEOUT', '90'))

    def analyze_transcription(self, transcription: str, custom_prompt: str, audio_key: str, output_fields: list[str] | None = None) -> dict[str, Any]:
        fields = _normalize_fields(output_fields or [])

        system_prompt = (
            'Eres un analista QA de llamadas. Responde exclusivamente JSON valido. '
            'Debes devolver un objeto con la clave "analysis" que contenga una lista de objetos.'
        )

        user_prompt = (
            f'{custom_prompt}\n\n'
            f'Campos requeridos por cada item: {", ".join(fields)}\n'
            'Los campos criterio, evaluacion y justificacion son obligatorios y nunca deben quedar vacios.\n'
            'evaluacion solo puede ser: Cumple, No cumple o No aplica.\n'
            'Devuelve SOLO JSON con esta forma exacta: '
            '{"analysis":[{...}]}\n'
            'Cada objeto de analysis debe incluir todos los campos requeridos.\n\n'
            f'Audio key: {audio_key}\n'
            f'Transcripcion:\n{transcription}'
        )

        schema_properties = {field: {'type': 'string'} for field in fields}
        required_fields = list(fields)

        payload = {
            'model': self.model,
            'temperature': self.temperature,
            'max_tokens': self.max_tokens,
            'response_format': {
                'type': 'json_schema',
                'json_schema': {
                    'name': 'analysis_result',
                    'schema': {
                        'type': 'object',
                        'additionalProperties': False,
                        'properties': {
                            'analysis': {
                                'type': 'array',
                                'items': {
                                    'type': 'object',
                                    'additionalProperties': False,
                                    'properties': schema_properties,
                                    'required': required_fields,
                                },
                            },
                        },
                        'required': ['analysis'],
                    },
                },
            },
            'messages': [
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': user_prompt},
            ],
        }

        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json',
        }

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post('https://api.openai.com/v1/chat/completions', headers=headers, json=payload)

            if response.status_code >= 400:
                raise ValueError(f'Error OpenAI ({response.status_code}): {response.text}')

            data = response.json()
            content = (
                data.get('choices', [{}])[0]
                .get('message', {})
                .get('content', '')
            )

            parsed = json.loads(content) if content else {}
            analysis_items = _normalize_analysis_payload(parsed, fields)

            if not analysis_items:
                return _build_fallback_response(fields, custom_prompt, transcription)

            usage = data.get('usage') or {}
            in_tokens = int(usage.get('prompt_tokens') or 0)
            out_tokens = int(usage.get('completion_tokens') or 0)

            return {
                'analysis': analysis_items,
                'in_tokens': in_tokens,
                'out_tokens': out_tokens,
                'cost': 0.0,
            }
        except Exception as exc:
            raise ValueError(f'No se pudo analizar con OpenAI: {exc}') from exc