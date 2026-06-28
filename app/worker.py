import os
import json
import subprocess
import tempfile

import boto3
import psycopg2

QUEUE_URL   = os.environ["QUEUE_URL"]
QUEUE_TYPE  = os.environ["QUEUE_TYPE"]   # "signed" or "free"
S3_BUCKET   = os.environ["S3_BUCKET"]
DB_HOST     = os.environ["DB_HOST"]
DB_NAME     = os.environ.get("DB_NAME", "projectview")
DB_USER     = os.environ["DB_USER"]
DB_PASSWORD = os.environ["DB_PASSWORD"]

TABLE = "signed_jobs" if QUEUE_TYPE == "signed" else "free_jobs"

sqs = boto3.client("sqs", region_name="us-east-1")
s3  = boto3.client("s3",  region_name="us-east-1")


def get_db():
    return psycopg2.connect(host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASSWORD, sslmode="require")


def init_db():
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS free_jobs (
            job_id     TEXT PRIMARY KEY,
            s3_key     TEXT,
            status     TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS signed_jobs (
            job_id     TEXT PRIMARY KEY,
            username   TEXT,
            s3_key     TEXT,
            status     TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    conn.commit()
    cur.close()
    conn.close()


def process(body, receipt_handle):
    job_id       = body["job_id"]
    s3_input_key = body["s3_input_key"]
    username     = body.get("username")

    conn = get_db()
    cur  = conn.cursor()

    try:
        if QUEUE_TYPE == "signed":
            cur.execute(
                "INSERT INTO signed_jobs (job_id, username, status) VALUES (%s, %s, 'pending')",
                (job_id, username),
            )
        else:
            cur.execute(
                "INSERT INTO free_jobs (job_id, status) VALUES (%s, 'pending')",
                (job_id,),
            )
        conn.commit()

        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, f"{job_id}.docx")

            s3.download_file(S3_BUCKET, s3_input_key, input_path)

            subprocess.run(
                ["libreoffice", "--headless", "--convert-to", "pdf", "--outdir", tmpdir, input_path],
                check=True,
                timeout=60,
            )

            output_path  = os.path.join(tmpdir, f"{job_id}.pdf")
            s3_output_key = f"outputs/{job_id}.pdf"
            s3.upload_file(output_path, S3_BUCKET, s3_output_key)

        cur.execute(
            f"UPDATE {TABLE} SET status = 'done', s3_key = %s WHERE job_id = %s",
            (s3_output_key, job_id),
        )
        conn.commit()
        print(f"[{QUEUE_TYPE}] done: {job_id}")

    except Exception as exc:
        print(f"[{QUEUE_TYPE}] failed: {job_id} — {exc}")
        cur.execute(f"UPDATE {TABLE} SET status = 'failed' WHERE job_id = %s", (job_id,))
        conn.commit()

    finally:
        cur.close()
        conn.close()
        sqs.delete_message(QueueUrl=QUEUE_URL, ReceiptHandle=receipt_handle)


def poll():
    print(f"[worker] starting — type={QUEUE_TYPE} table={TABLE}")
    init_db()
    while True:
        resp     = sqs.receive_message(QueueUrl=QUEUE_URL, MaxNumberOfMessages=1, WaitTimeSeconds=20)
        messages = resp.get("Messages", [])
        if not messages:
            continue
        msg = messages[0]
        print(f"[{QUEUE_TYPE}] received job {json.loads(msg['Body']).get('job_id')}")
        process(json.loads(msg["Body"]), msg["ReceiptHandle"])


if __name__ == "__main__":
    poll()
