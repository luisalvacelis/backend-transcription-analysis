from dotenv import load_dotenv
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / '.env')

from app.components.connection import Base, engine

# Create all tables
Base.metadata.create_all(bind=engine)

print("Tables created successfully!")