import os
import psycopg2
from psycopg2.extras import DictCursor
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from dotenv import load_dotenv



load_dotenv()

#General timezone configuration.
RUN_TIMEZONE_CHECK = os.getenv('RUN_TIMEZONE_CHECK', '1') == '1'

TZ_INFO = os.getenv("TZ", "America/Argentina/Buenos_Aires")
tz = ZoneInfo(TZ_INFO)



# Creating the DB connection. Prepared for the docker-compose.
def get_db_connection():
    print("POSTGRES_HOST=",os.getenv("POSTGRES_HOST", "DEFAULT"))
    print("POSTGRES_DB=",os.getenv("POSTGRES_DB", "DEFAULT"))
    print("POSTGRES_USER=",os.getenv("POSTGRES_USER", "DEFAULT"))
    print("POSTGRES_PASSWORD=",os.getenv("POSTGRES_PASSWORD", "DEFAULT"))

    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "postgres"),
        database=os.getenv("POSTGRES_DB", "messiXpert_assistant"),
        user=os.getenv("POSTGRES_USER", "admin"),
        password=os.getenv("POSTGRES_PASSWORD", "admin"),
    )



# Initaliazing the database. Creating the tables needed for monitoring.
def init_db():
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS feedbacks")
            cur.execute("DROP TABLE IF EXISTS answers")

            cur.execute("""
                CREATE TABLE answers (
                    id TEXT PRIMARY KEY,
                    question TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    model_used TEXT NOT NULL,
                    response_time FLOAT NOT NULL,
                    relevance TEXT NOT NULL,
                    relevance_explanation TEXT NOT NULL,
                    prompt_tokens INTEGER NOT NULL,
                    completion_tokens INTEGER NOT NULL,
                    total_tokens INTEGER NOT NULL,
                    eval_prompt_tokens INTEGER NOT NULL,
                    eval_completion_tokens INTEGER NOT NULL,
                    eval_total_tokens INTEGER NOT NULL,
                    openai_cost FLOAT NOT NULL,
                    timestamp TIMESTAMP WITH TIME ZONE NOT NULL
                )
            """)
            cur.execute("""
                CREATE TABLE feedbacks (
                    id SERIAL PRIMARY KEY,
                    answer_id TEXT REFERENCES answers(id),
                    feedback INTEGER NOT NULL,
                    timestamp TIMESTAMP WITH TIME ZONE NOT NULL
                )
            """)
        conn.commit()
    finally:
        conn.close()



# Adding an answer row to the database
def save_answer(conversation_id, answer_data, timestamp=None):
    if timestamp is None:
        timestamp = datetime.now(tz)

    conn = get_db_connection()
    try:
        print("SAVING ANSWER DB")
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO answers 
                (id, question, answer, model_used, response_time, relevance, 
                relevance_explanation, prompt_tokens, completion_tokens, total_tokens, 
                eval_prompt_tokens, eval_completion_tokens, eval_total_tokens, openai_cost, timestamp)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    conversation_id,
                    answer_data["question"],
                    answer_data["answer"],
                    answer_data["model_used"],
                    answer_data["response_time"],
                    answer_data["relevance"],
                    answer_data["relevance_explanation"],
                    answer_data["prompt_tokens"],
                    answer_data["completion_tokens"],
                    answer_data["total_tokens"],
                    answer_data["eval_prompt_tokens"],
                    answer_data["eval_completion_tokens"],
                    answer_data["eval_total_tokens"],
                    answer_data["openai_cost"],
                    timestamp
                ),
            )
        conn.commit()
        print("SAVED ANSWER DB")
    finally:
        conn.close()
        print("SAVED AND CLOSED ANSWER DB")



# Saving user feedback to the database
def save_feedback(conversation_id, feedback, timestamp=None):
    if timestamp is None:
        timestamp = datetime.now(tz)

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO feedbacks (answer_id, feedback, timestamp) VALUES (%s, %s, COALESCE(%s, CURRENT_TIMESTAMP))",
                (conversation_id, feedback, timestamp),
            )
        conn.commit()
    finally:
        conn.close()



# Get the last conversations with the wanted limit and filtered by relevance if wanted
def get_last_conversations(limit=5, relevance=None):
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            query = """
                SELECT answers.*, feedbacks.feedback
                FROM answers
                LEFT JOIN feedbacks ON answers.id = feedbacks.answers_id
            """
            if relevance:
                query += f" WHERE answers.relevance = '{relevance}'"
            query += " ORDER BY answers.timestamp DESC LIMIT %s"

            cur.execute(query, (limit,))
            return cur.fetchall()
    finally:
        conn.close()



# Get total feedback stats
def get_feedback_stats():
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute("""
                SELECT 
                    SUM(CASE WHEN feedback > 0 THEN 1 ELSE 0 END) as thumbs_up,
                    SUM(CASE WHEN feedback < 0 THEN 1 ELSE 0 END) as thumbs_down
                FROM feedbacks
            """)
            return cur.fetchone()
    finally:
        conn.close()



# Check the configured timezone
def check_timezone():
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SHOW timezone;")
            db_timezone = cur.fetchone()[0]
            print(f"Database timezone: {db_timezone}")

            cur.execute("SELECT current_timestamp;")
            db_time_utc = cur.fetchone()[0]
            print(f"Database current time (UTC): {db_time_utc}")

            db_time_local = db_time_utc.astimezone(tz)
            print(f"Database current time ({TZ_INFO}): {db_time_local}")

            py_time = datetime.now(tz)
            print(f"Python current time: {py_time}")

            # Use py_time instead of tz for insertion
            cur.execute("""
                INSERT INTO answers 
                (id, question, answer, model_used, response_time, relevance, 
                relevance_explanation, prompt_tokens, completion_tokens, total_tokens, 
                eval_prompt_tokens, eval_completion_tokens, eval_total_tokens, openai_cost, timestamp)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING timestamp;
            """, 
            ('test', 'test question', 'test answer', 'test model', 0.0, 0.0, 
             'test explanation', 0, 0, 0, 0, 0, 0, 0.0, py_time))

            inserted_time = cur.fetchone()[0]
            print(f"Inserted time (UTC): {inserted_time}")
            print(f"Inserted time ({TZ_INFO}): {inserted_time.astimezone(tz)}")

            cur.execute("SELECT timestamp FROM answers WHERE id = 'test';")
            selected_time = cur.fetchone()[0]
            print(f"Selected time (UTC): {selected_time}")
            print(f"Selected time ({TZ_INFO}): {selected_time.astimezone(tz)}")

            # Clean up the test entry
            cur.execute("DELETE FROM answers WHERE id = 'test';")
            conn.commit()
    except Exception as e:
        print(f"An error occurred: {e}")
        conn.rollback()
    finally:
        conn.close()




if RUN_TIMEZONE_CHECK:
    check_timezone()