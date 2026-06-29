import os
os.environ["QUEUE_URL"]   = "https://sqs.us-east-1.amazonaws.com/123/free"
os.environ["QUEUE_TYPE"]  = "free"
os.environ["S3_BUCKET"]   = "test-bucket"
os.environ["DB_HOST"]     = "localhost"
os.environ["DB_USER"]     = "test"
os.environ["DB_PASSWORD"] = "test"

import pytest
from unittest.mock import patch, MagicMock

with patch("boto3.client"):
    from worker import process, TABLE


def make_db_mock():
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    return mock_conn, mock_cursor


def test_process_inserts_pending_then_done():
    mock_conn, mock_cursor = make_db_mock()
    body = {"job_id": "job-123", "s3_input_key": "uploads/job-123.docx"}

    with patch("worker.get_db", return_value=mock_conn), \
         patch("worker.s3"), \
         patch("worker.sqs") as mock_sqs, \
         patch("subprocess.run"):
        process(body, "receipt-handle-abc")

        first_call = mock_cursor.execute.call_args_list[0]
        assert "INSERT" in first_call.args[0]
        assert "pending" in first_call.args[0]

        last_call = mock_cursor.execute.call_args_list[-1]
        assert "done" in last_call.args[0]

        mock_sqs.delete_message.assert_called_once()


def test_process_marks_failed_on_exception():
    mock_conn, mock_cursor = make_db_mock()
    body = {"job_id": "job-456", "s3_input_key": "uploads/job-456.docx"}

    with patch("worker.get_db", return_value=mock_conn), \
         patch("worker.s3") as mock_s3, \
         patch("worker.sqs") as mock_sqs:
        mock_s3.download_file.side_effect = Exception("S3 unreachable")
        process(body, "receipt-handle-xyz")

        last_call = mock_cursor.execute.call_args_list[-1]
        assert "failed" in last_call.args[0]

        mock_sqs.delete_message.assert_called_once()


def test_table_is_free_jobs_for_free_queue():
    assert TABLE == "free_jobs"
