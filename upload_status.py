from __future__ import annotations

import os
import threading
import time
from typing import Any


_lock = threading.RLock()

_jobs: dict[str, dict[str, Any]] = {}

_path_to_job: dict[str, str] = {}


def normalize_path(path: str) -> str:
    return os.path.normcase(
        os.path.abspath(
            os.path.normpath(path)
        )
    )


def create_job(
    job_id: str,
    filename: str,
    file_path: str,
) -> None:

    normalized_path = normalize_path(file_path)

    with _lock:
        _jobs[job_id] = {
            "job_id": job_id,
            "filename": filename,
            "file_path": normalized_path,
            "status": "uploaded",
            "message": "Файл загружен и ожидает обработки",
            "created_at": time.time(),
            "updated_at": time.time(),
        }

        _path_to_job[normalized_path] = job_id


def update_job(
    job_id: str,
    status: str,
    message: str,
) -> None:

    with _lock:

        job = _jobs.get(job_id)

        if job is None:
            return

        job["status"] = status
        job["message"] = message
        job["updated_at"] = time.time()


def update_job_by_path(
    file_path: str,
    status: str,
    message: str,
) -> None:

    normalized_path = normalize_path(file_path)

    with _lock:
        job_id = _path_to_job.get(normalized_path)

    if job_id:
        update_job(
            job_id,
            status,
            message,
        )


def get_job(job_id: str) -> dict[str, Any] | None:

    with _lock:

        job = _jobs.get(job_id)

        if job is None:
            return None

        return dict(job)


def get_jobs(
    job_ids: list[str],
) -> list[dict[str, Any]]:

    with _lock:

        result = []

        for job_id in job_ids:

            job = _jobs.get(job_id)

            if job is not None:
                result.append(dict(job))

        return result


def remove_job(job_id: str) -> None:

    with _lock:

        job = _jobs.pop(job_id, None)

        if job is not None:

            file_path = job.get("file_path")

            if file_path:
                _path_to_job.pop(
                    normalize_path(file_path),
                    None,
                )
