from __future__ import annotations

from pathlib import Path
import os
import re
from typing import Any, cast

from dotenv import load_dotenv
from sqlalchemy import select


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / '.env', override=True)

MODEL_PROMPTS_FILE = Path(
    os.getenv(
        'MODEL_PROMPTS_FILE',
        r'c:\Users\Luis\Documents\.repositorios_github\python\valtx_transcription_analysis\components\deepgram_openai_component.py',
    )
)

from app.components.models import PromptTemplate, User  # pyright: ignore[reportMissingImports]
from app.components.connection import SessionLocal

PROMPT_NAMES = {
    1: 'TC Venta Amigable BBVA',
    2: 'Seguro Renta Hospitalaria',
    3: 'Seguro Proteccion Multiple',
    5: 'Migraciones Tarjetas BBVA',
    7: 'PAT Desembolso Digital',
    9: 'Subrogado',
}

EXCLUDED_PROMPT_NAMES = {
    'Scotiabank TC No Venta',
    'Scotiabank TC Mala Gestion',
    'Vector Store Reclamos BBVA',
}

PROMPT_PATTERN = re.compile(
    r'case\s+(?P<case>\d+)\s*:\s*.*?CALIDAD_PROMPT\s*=\s*"""(?P<prompt>.*?)"""',
    re.S,
)


def _extract_subrogado_prompt(source_text: str) -> str | None:
    marker = '#Subrogado'
    marker_index = source_text.find(marker)
    if marker_index == -1:
        return None

    prompt_start = source_text.find('CALIDAD_PROMPT = """', marker_index)
    if prompt_start == -1:
        return None

    prompt_start += len('CALIDAD_PROMPT = """')
    prompt_end = source_text.find('"""', prompt_start)
    if prompt_end == -1:
        return None

    return source_text[prompt_start:prompt_end].strip()


def extract_model_prompts() -> list[dict[str, str]]:
    if not MODEL_PROMPTS_FILE.exists():
        raise FileNotFoundError(f'No existe el archivo modelo: {MODEL_PROMPTS_FILE}')

    source_text = MODEL_PROMPTS_FILE.read_text(encoding='utf-8')
    matches = PROMPT_PATTERN.finditer(source_text)

    prompts: list[dict[str, str]] = []
    found_cases: set[int] = set()

    for match in matches:
        case_number = int(match.group('case'))
        prompt_text = match.group('prompt').strip()
        prompt_name = PROMPT_NAMES.get(case_number)

        if prompt_name is None:
            continue

        found_cases.add(case_number)
        prompts.append(
            {
                'name': prompt_name,
                'prompt_text': prompt_text,
            }
        )

    if 9 in PROMPT_NAMES and all(item['name'] != PROMPT_NAMES[9] for item in prompts):
        subrogado_prompt = _extract_subrogado_prompt(source_text)
        if subrogado_prompt is not None:
            prompts.append(
                {
                    'name': PROMPT_NAMES[9],
                    'prompt_text': subrogado_prompt,
                }
            )
            found_cases.add(9)

    expected_cases = set(PROMPT_NAMES)
    missing_cases = sorted(expected_cases - found_cases)
    if missing_cases:
        raise RuntimeError(f'No se pudieron extraer los casos esperados del archivo modelo: {missing_cases}')

    prompts.sort(key=lambda item: next(case for case, name in PROMPT_NAMES.items() if name == item['name']))
    return prompts


def seed_prompts() -> None:
    prompts = extract_model_prompts()

    with SessionLocal() as session:
        session.query(PromptTemplate).filter(PromptTemplate.name.in_(EXCLUDED_PROMPT_NAMES)).delete(synchronize_session=False)
        users = session.execute(select(User)).scalars().all()

        created = 0
        updated = 0

        for user in users:
            for prompt_data in prompts:
                existing = (
                    session.query(PromptTemplate)
                    .filter(
                        PromptTemplate.user_id == user.id,
                        PromptTemplate.name == prompt_data['name'],
                    )
                    .first()
                )

                if existing:
                    existing_model = cast(Any, existing)
                    existing_model.prompt_text = prompt_data['prompt_text']
                    existing_model.is_active = True
                    updated += 1
                    continue

                session.add(
                    PromptTemplate(
                        user_id=user.id,
                        name=prompt_data['name'],
                        prompt_text=prompt_data['prompt_text'],
                        is_active=True,
                    )
                )
                created += 1

        session.commit()
        print(f'Prompts creados: {created}')
        print(f'Prompts actualizados: {updated}')
        print(f'Usuarios procesados: {len(users)}')


if __name__ == '__main__':
    seed_prompts()
