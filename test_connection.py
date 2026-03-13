#!/usr/bin/env python
from dotenv import load_dotenv
from pathlib import Path
import os
from sqlalchemy import text

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / '.env', override=True)

print("=" * 60)
print("VERIFICACIÓN DE CONEXIÓN A BASE DE DATOS")
print("=" * 60)

# Verificar variables de entorno
print("\n1. VARIABLES DE ENTORNO:")
db_url = os.getenv('DATABASE_URL')
print(f"   DATABASE_URL: {db_url}")

# Intentar conexión
print("\n2. PRUEBA DE CONEXIÓN:")
try:
    from app.components.connection import engine
    with engine.connect() as conn:
        result = conn.execute(text("SELECT 1"))
        print("   ✅ Conexión exitosa a PostgreSQL")
        
        # Verificar tablas
        print("\n3. VERIFICACIÓN DE TABLAS:")
        result = conn.execute(text("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
            ORDER BY table_name
        """))
        tables = result.fetchall()
        if tables:
            print("   Tablas encontradas:")
            for table in tables:
                print(f"      ✓ {table[0]}")
        else:
            print("   ⚠️  No hay tablas en la base de datos")
        
        # Verificar usuarios
        print("\n4. VERIFICACIÓN DE DATOS EN tbl_users:")
        result = conn.execute(text("SELECT COUNT(*) FROM tbl_users"))
        count = result.fetchone()[0]
        print(f"   Total de usuarios: {count}")
        
except Exception as e:
    print(f"   ❌ Error de conexión: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 60)
