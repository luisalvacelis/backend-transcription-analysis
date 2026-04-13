from __future__ import annotations

import argparse
import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import select

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / '.env', override=True)

from app.components.connection import Base, SessionLocal, engine
from app.components.models import PromptTemplate, User
from app.utils.security_utils import hash_password
from seed_analysis_prompts import EXCLUDED_PROMPT_NAMES, extract_model_prompts


def _get_seed_credentials() -> tuple[str, str]:
    username = os.getenv('SEED_DEFAULT_USERNAME', 'luisalvacelis').strip()
    password = os.getenv('SEED_DEFAULT_PASSWORD', '123asd123').strip()

    if not username or not password:
        raise RuntimeError(
            'SEED_DEFAULT_USERNAME y SEED_DEFAULT_PASSWORD deben tener valor para crear el usuario base.'
        )

    return username, password


def _upsert_default_user(session) -> User:
    username, password = _get_seed_credentials()
    existing_user = session.execute(select(User).where(User.username == username)).scalar_one_or_none()

    if existing_user:
        existing_user.password = hash_password(password)
        return existing_user

    user = User(username=username, password=hash_password(password))
    session.add(user)
    session.flush()
    return user


def _seed_prompts_for_all_users(session) -> tuple[int, int, int]:
    prompts = extract_model_prompts()
    users = session.execute(select(User)).scalars().all()

    session.query(PromptTemplate).filter(PromptTemplate.name.in_(EXCLUDED_PROMPT_NAMES)).delete(synchronize_session=False)

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
                existing.prompt_text = prompt_data['prompt_text']
                existing.is_active = True
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

    return created, updated, len(users)


def recreate_tables(drop_existing: bool) -> None:
    if drop_existing:
        Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Recrea tablas y siembra datos base (usuario + prompts) usando .env.'
    )
    parser.add_argument(
        '--keep-existing',
        action='store_true',
        help='No elimina tablas existentes; solo crea faltantes y actualiza seeds.',
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if not os.getenv('DATABASE_URL'):
        raise RuntimeError('DATABASE_URL no esta configurada en el entorno del backend')

    recreate_tables(drop_existing=not args.keep_existing)

    with SessionLocal() as session:
        user = _upsert_default_user(session)
        created, updated, user_count = _seed_prompts_for_all_users(session)
        session.commit()

    print('Proceso completado correctamente')
    print(f'Usuario base listo: {user.username}')
    print(f'Prompts creados: {created}')
    print(f'Prompts actualizados: {updated}')
    print(f'Usuarios procesados: {user_count}')


if __name__ == '__main__':
    main()