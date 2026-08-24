from __future__ import annotations

import os
import uuid
from pathlib import Path

from flask import (
    Flask,
    render_template,
    request,
    jsonify,
)

from waitress import serve

from config import (
    ALLOWED_SORT_FIELDS,
    UPLOAD_FOLDER,
)

from db import (
    init_db,
    get_db_connection,
)

from watchdog_handler import start_watchdog

from upload_status import (
    create_job,
    get_job,
    get_jobs,
)


app = Flask(__name__)

app.secret_key = (
    "supersecretkey_change_in_production"
)


UPLOAD_PATH = Path(
    UPLOAD_FOLDER
).resolve()


@app.route("/")
def index():

    page = request.args.get(
        "page",
        1,
        type=int,
    )

    per_page = request.args.get(
        "per_page",
        50,
        type=int,
    )

    offset = (
        page - 1
    ) * per_page

    search = request.args.get(
        "search",
        "",
    ).strip()

    q_shpi = (
        request.args.get(
            "q_shpi"
        )
        is not None
    )

    q_recipient = (
        request.args.get(
            "q_recipient"
        )
        is not None
    )

    q_address = (
        request.args.get(
            "q_address"
        )
        is not None
    )

    q_comment = (
        request.args.get(
            "q_comment"
        )
        is not None
    )

    date_from = request.args.get(
        "dateFrom",
        "",
    ).strip()

    date_to = request.args.get(
        "dateTo",
        "",
    ).strip()

    sort_by = request.args.get(
        "sortBy",
        "id",
    )

    order = request.args.get(
        "order",
        "desc",
    ).lower()

    if sort_by not in ALLOWED_SORT_FIELDS:
        sort_by = "id"

    order_norm = (
        "DESC"
        if order == "desc"
        else "ASC"
    )

    conn = get_db_connection()

    cur = conn.cursor()

    base_query = (
        "SELECT * FROM shipments"
    )

    where_clauses = []

    params = []

    if search:

        search_pattern = (
            f"%{search}%"
        )

        fields_to_search = []

        if q_shpi:

            fields_to_search.append(
                "shpi LIKE ?"
            )

            params.append(
                search_pattern
            )

        if q_recipient:

            fields_to_search.append(
                "recipient LIKE ?"
            )

            params.append(
                search_pattern
            )

        if q_address:

            fields_to_search.append(
                "address LIKE ?"
            )

            params.append(
                search_pattern
            )

        if q_comment:

            fields_to_search.append(
                "comment LIKE ?"
            )

            params.append(
                search_pattern
            )

        if fields_to_search:

            where_clauses.append(
                "("
                + " OR ".join(
                    fields_to_search
                )
                + ")"
            )

    if date_from:

        where_clauses.append(
            "uploaded_at >= ?"
        )

        params.append(
            date_from
        )

    if date_to:

        where_clauses.append(
            "uploaded_at <= ?"
        )

        params.append(
            f"{date_to} 23:59:59"
        )

    where = (
        " WHERE "
        + " AND ".join(
            where_clauses
        )
        if where_clauses
        else ""
    )

    count_query = (
        "SELECT COUNT(*) AS total "
        f"FROM shipments{where}"
    )

    cur.execute(
        count_query,
        params,
    )

    total = cur.fetchone()["total"]

    query = (
        f"{base_query}"
        f"{where} "
        f"ORDER BY {sort_by} "
        f"{order_norm} "
        "LIMIT ? OFFSET ?"
    )

    query_params = (
        params
        + [
            per_page,
            offset,
        ]
    )

    cur.execute(
        query,
        query_params,
    )

    rows = cur.fetchall()

    conn.close()

    shipments = [
        dict(row)
        for row in rows
    ]

    total_pages = max(
        1,
        (
            total
            + per_page
            - 1
        )
        // per_page,
    )

    return render_template(
        "PartPostCrimea.html",
        shipments=shipments,
        current_page=page,
        total_pages=total_pages,
        total_count=total,
        per_page=per_page,
        search=search,
        date_from=date_from,
        date_to=date_to,
        q_shpi=q_shpi,
        q_recipient=q_recipient,
        q_address=q_address,
        q_comment=q_comment,
        sortBy=sort_by,
        order=order,
    )


@app.route("/upload-page")
def upload_page():

    return render_template(
        "UploadPage.html"
    )


@app.route(
    "/upload",
    methods=["POST"],
)
def upload_file():

    UPLOAD_PATH.mkdir(
        parents=True,
        exist_ok=True,
    )

    files = request.files.getlist(
        "files"
    )

    if not files:

        single_file = request.files.get(
            "file"
        )

        if single_file:
            files = [single_file]

    if not files:

        return jsonify({
            "success": False,
            "error": "Файлы не выбраны",
        }), 400

    jobs = []

    for uploaded_file in files:

        if not uploaded_file:
            continue

        original_name = (
            uploaded_file.filename
            or ""
        ).strip()

        if not original_name:
            continue

        extension = (
            Path(original_name)
            .suffix
            .lower()
        )

        if extension not in {
            ".xlsx",
            ".xls",
        }:

            jobs.append({
                "success": False,
                "filename": original_name,
                "error": (
                    "Поддерживаются "
                    "только .xlsx и .xls"
                ),
            })

            continue

        job_id = uuid.uuid4().hex

        safe_name = (
            f"{job_id}_{Path(original_name).name}"
        )

        destination = (
            UPLOAD_PATH
            / safe_name
        )

        try:

            uploaded_file.save(
                str(destination)
            )

            create_job(
                job_id=job_id,
                filename=original_name,
                file_path=str(
                    destination
                ),
            )

            jobs.append({
                "success": True,
                "job_id": job_id,
                "filename": original_name,
                "status": "uploaded",
                "message": (
                    "Файл загружен "
                    "и ожидает обработки"
                ),
            })

            print(
                "[UPLOAD] Загружен файл: "
                f"{original_name} "
                f"→ {destination}"
            )

        except Exception as error:

            jobs.append({
                "success": False,
                "filename": original_name,
                "error": str(error),
            })

    successful = [
        job
        for job in jobs
        if job.get("success")
    ]

    if not successful:

        return jsonify({
            "success": False,
            "jobs": jobs,
        }), 400

    return jsonify({
        "success": True,
        "jobs": jobs,
    })


@app.route(
    "/upload/status/<job_id>",
)
def upload_status(job_id):

    job = get_job(job_id)

    if job is None:

        return jsonify({
            "success": False,
            "error": "Задание не найдено",
        }), 404

    return jsonify({
        "success": True,
        "job": job,
    })


@app.route(
    "/upload/status",
)
def upload_status_batch():

    job_ids = request.args.getlist(
        "job_id"
    )

    if not job_ids:

        return jsonify({
            "success": False,
            "error": "Не переданы job_id",
        }), 400

    return jsonify({
        "success": True,
        "jobs": get_jobs(
            job_ids
        ),
    })


if __name__ == "__main__":

    UPLOAD_PATH.mkdir(
        parents=True,
        exist_ok=True,
    )

    print(
        "[INIT] Папка uploads: "
        f"{UPLOAD_PATH}"
    )

    init_db()

    observer = start_watchdog(
        UPLOAD_PATH
    )

    try:

        serve(
            app,
            host="0.0.0.0",
            port=5000,
            threads=8,
        )

    except KeyboardInterrupt:

        print(
            "[SERVER] Остановка..."
        )

        observer.stop()

    observer.join()
