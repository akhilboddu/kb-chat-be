from app.core.db_manager import get_postgres_db


def post_message(conversation_id: str, message: str, role: str):
    try:
        with get_postgres_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO messages (conversation_id, content, role)
                VALUES (%s, %s, %s);
                """,
                (conversation_id, message, role),
            )
            conn.commit()  # commit the insert
            return True  # or return inserted data if you use RETURNING *

    except Exception as e:
        print(f"Error inserting message: {e}")
        return False
