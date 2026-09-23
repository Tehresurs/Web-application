import os

import psycopg
from dotenv import load_dotenv

load_dotenv()


def get_connection():
    return psycopg.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
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
