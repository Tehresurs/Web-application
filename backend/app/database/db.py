import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

_backend_dir = Path(__file__).resolve().parents[2]
load_dotenv(_backend_dir / ".env")

if os.getenv("APP_DB_PROFILE") == "test":
    test_env = _backend_dir / ".env.test"
    if not test_env.is_file():
        raise RuntimeError(f"Test database configuration not found: {test_env}")
    load_dotenv(test_env, override=True)


def get_connection():
    connection_options = {}
    if os.getenv("APP_DB_PROFILE") == "test":
        database = os.getenv("DB_NAME")
        schema = os.getenv("DB_SCHEMA")
        if database != "ai_excel_agent_test":
            raise RuntimeError(f"Refusing test profile database: {database!r}")
        if not schema or not schema.replace("_", "").isalnum() or not schema.startswith("test_"):
            raise RuntimeError(f"Refusing invalid test profile schema: {schema!r}")
        connection_options["options"] = f"-c search_path={schema}"
    return psycopg.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        **connection_options,
    )


def test_connection():
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT current_database();")
                database_name = cursor.fetchone()[0]

                print("Подключение к PostgreSQL успешно")
                print(f"База данных: {database_name}")

    except Exception as error:
        print("Ошибка подключения к PostgreSQL:")
        print(error)


if __name__ == "__main__":
    test_connection()
