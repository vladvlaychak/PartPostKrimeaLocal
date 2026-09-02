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
    normalize_internal_number,
)

from watchdog_handler import start_watchdog

from upload_status import (
    create_job,
    get_job,
    get_jobs,
)


# ============================================================
# FLASK
# ============================================================

app = Flask(__name__)

app.secret_key = (
    "supersecretkey_change_in_production"
)


# ============================================================
# UPLOAD FOLDER
# ============================================================

UPLOAD_PATH = Path(
    UPLOAD_FOLDER
).resolve()


UPLOAD_PATH.mkdir(
    parents=True,
    exist_ok=True,
)


# ============================================================
# ОСНОВНАЯ СТРАНИЦА
# ============================================================

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
    search_pattern = f"%{search}%"
    fields_to_search = []

    if q_shpi:
        fields_to_search.append("shpi LIKE ?")
        params.append(search_pattern)

    if q_recipient:
        fields_to_search.append("recipient LIKE ?")
        params.append(search_pattern)

    if q_address:
        fields_to_search.append("address LIKE ?")
        params.append(search_pattern)

    if q_comment:
        fields_to_search.append("comment LIKE ?")
        params.append(search_pattern)

    # Поиск по внутреннему (исходящему) номеру
    internal_search = normalize_internal_number(search)

    if internal_search:
        fields_to_search.append(
            "internal_number_normalized LIKE ?"
        )
        params.append(f"%{internal_search}%")

    if fields_to_search:
        where_clauses.append(
            "(" + " OR ".join(fields_to_search) + ")"
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


# ============================================================
# СТРАНИЦА ЗАГРУЗКИ
# ============================================================

@app.route("/upload-page")
def upload_page():

    return render_template(
        "UploadPage.html"
    )


# ============================================================
# ЗАГРУЗКА ОДНОГО ИЛИ НЕСКОЛЬКИХ ФАЙЛОВ
# ============================================================

@app.route(
    "/upload",
    methods=["POST"],
)
def upload_file():

    UPLOAD_PATH.mkdir(
        parents=True,
        exist_ok=True,
    )

    # --------------------------------------------------------
    # Основной вариант:
    #
    # FormData:
    #
    # files = file1
    # files = file2
    # files = file3
    # --------------------------------------------------------

    files = request.files.getlist(
        "files"
    )

    # --------------------------------------------------------
    # Поддержка старой формы:
    #
    # file = file
    # --------------------------------------------------------

    if not files:

        single_file = (
            request.files.get(
                "file"
            )
        )

        if single_file:

            files = [
                single_file
            ]

    # --------------------------------------------------------
    # Ничего не передали
    # --------------------------------------------------------

    if not files:

        return jsonify({
            "success": False,
            "error": (
                "Файлы не выбраны"
            ),
            "jobs": [],
        }), 400

    jobs = []

    # ========================================================
    # ОБРАБАТЫВАЕМ КАЖДЫЙ ФАЙЛ
    # ========================================================

    for uploaded_file in files:

        if not uploaded_file:

            continue

        original_name = (
            uploaded_file.filename
            or ""
        ).strip()

        if not original_name:

            continue

        # ----------------------------------------------------
        # Безопасное имя
        # ----------------------------------------------------

        original_path = Path(
            original_name
        )

        clean_name = (
            original_path.name
        )

        extension = (
            original_path
            .suffix
            .lower()
        )

        # ----------------------------------------------------
        # Проверка расширения
        # ----------------------------------------------------

        if extension not in {
            ".xlsx",
            ".xls",
        }:

            jobs.append({

                "success": False,

                "filename": clean_name,

                "status": "error",

                "message": (
                    "Неподдерживаемый "
                    "формат. Разрешены "
                    ".xlsx и .xls"
                ),

            })

            continue

        # ----------------------------------------------------
        # Создаём уникальный ID
        # ----------------------------------------------------

        job_id = uuid.uuid4().hex

        # ----------------------------------------------------
        # Имя файла внутри uploads
        #
        # Например:
        #
        # 5f8c..._file.xlsx
        # ----------------------------------------------------

        stored_name = (
            f"{job_id}_{clean_name}"
        )

        destination = (
            UPLOAD_PATH
            / stored_name
        )

        try:

            # ------------------------------------------------
            # Сохраняем файл
            # ------------------------------------------------

            uploaded_file.save(
                str(destination)
            )

            # ------------------------------------------------
            # Проверяем, что файл реально существует
            # ------------------------------------------------

            if not destination.exists():

                raise OSError(
                    "Файл не был создан "
                    "в папке uploads"
                )

            # ------------------------------------------------
            # Проверяем размер
            # ------------------------------------------------

            file_size = (
                destination.stat()
                .st_size
            )

            if file_size <= 0:

                raise OSError(
                    "Загруженный файл "
                    "имеет размер 0 байт"
                )

            # ------------------------------------------------
            # Создаём job
            # ------------------------------------------------

            create_job(
                job_id=job_id,
                filename=clean_name,
                file_path=str(
                    destination
                ),
            )

            jobs.append({

                "success": True,

                "job_id": job_id,

                "filename": clean_name,

                "status": "uploaded",

                "message": (
                    "Файл загружен "
                    "и ожидает обработки"
                ),

                "size": file_size,

            })

            print(
                "[UPLOAD] "
                f"✓ {clean_name}"
            )

            print(
                "[UPLOAD] Job ID: "
                f"{job_id}"
            )

            print(
                "[UPLOAD] Path: "
                f"{destination}"
            )

            print(
                "[UPLOAD] Size: "
                f"{file_size} bytes"
            )

        except Exception as error:

            print(
                "[UPLOAD] "
                f"✗ Ошибка {clean_name}: "
                f"{error}"
            )

            # ------------------------------------------------
            # Если файл частично создался —
            # удаляем его
            # ------------------------------------------------

            try:

                if destination.exists():

                    destination.unlink()

            except Exception:

                pass

            jobs.append({

                "success": False,

                "filename": clean_name,

                "status": "error",

                "message": (
                    f"{type(error).__name__}: "
                    f"{error}"
                ),

            })

    # ========================================================
    # РЕЗУЛЬТАТ
    # ========================================================

    successful_jobs = [
        job
        for job in jobs
        if job.get(
            "success"
        )
    ]

    failed_jobs = [
        job
        for job in jobs
        if not job.get(
            "success"
        )
    ]

    # --------------------------------------------------------
    # Ни одного успешного файла
    # --------------------------------------------------------

    if not successful_jobs:

        return jsonify({

            "success": False,

            "jobs": jobs,

            "total": len(jobs),

            "uploaded": 0,

            "errors": len(
                failed_jobs
            ),

            "message": (
                "Ни один файл "
                "не был загружен"
            ),

        }), 400

    # --------------------------------------------------------
    # Есть успешные файлы
    # --------------------------------------------------------

    return jsonify({

        "success": True,

        "jobs": jobs,

        "total": len(jobs),

        "uploaded": len(
            successful_jobs
        ),

        "errors": len(
            failed_jobs
        ),

        "message": (
            f"Загружено файлов: "
            f"{len(successful_jobs)}"
        ),

    })


# ============================================================
# СТАТУС ОДНОГО ФАЙЛА
# ============================================================

@app.route(
    "/upload/status/<job_id>",
    methods=["GET"],
)
def upload_status(job_id):

    job = get_job(
        job_id
    )

    if job is None:

        return jsonify({

            "success": False,

            "error": (
                "Задание не найдено"
            ),

        }), 404

    return jsonify({

        "success": True,

        "job": job,

    })


# ============================================================
# СТАТУС НЕСКОЛЬКИХ ФАЙЛОВ
# ============================================================

@app.route(
    "/upload/status",
    methods=["GET"],
)
def upload_status_batch():

    job_ids = request.args.getlist(
        "job_id"
    )

    if not job_ids:

        return jsonify({

            "success": False,

            "error": (
                "Не переданы job_id"
            ),

            "jobs": [],

        }), 400

    jobs = get_jobs(
        job_ids
    )

    return jsonify({

        "success": True,

        "jobs": jobs,

    })


# ============================================================
# HEALTH CHECK
# ============================================================

@app.route(
    "/health",
    methods=["GET"],
)
def health():

    return jsonify({

        "success": True,

        "status": "ok",

        "upload_folder": str(
            UPLOAD_PATH
        ),

        "upload_folder_exists":
            UPLOAD_PATH.exists(),

    })


# ============================================================
# ЗАПУСК
# ============================================================

def main():

    print()
    print(
        "=========================================="
    )

    print(
        " PartPostKrimeaLocal"
    )

    print(
        "=========================================="
    )

    print(
        "[INIT] Upload folder:"
    )

    print(
        f"       {UPLOAD_PATH}"
    )

    # --------------------------------------------------------
    # Создаём uploads
    # --------------------------------------------------------

    UPLOAD_PATH.mkdir(
        parents=True,
        exist_ok=True,
    )

    # --------------------------------------------------------
    # Инициализируем БД
    # --------------------------------------------------------

    print(
        "[INIT] Инициализация БД..."
    )

    init_db()

    print(
        "[INIT] БД готова"
    )

    # --------------------------------------------------------
    # Запускаем watchdog
    # --------------------------------------------------------

    print(
        "[INIT] Запуск watchdog..."
    )

    observer = start_watchdog(
        UPLOAD_PATH
    )

    print(
        "[INIT] Watchdog запущен"
    )

    # --------------------------------------------------------
    # Запускаем Flask / Waitress
    # --------------------------------------------------------

    print(
        "[SERVER] Запуск сервера..."
    )

    print(
        "[SERVER] http://127.0.0.1:5000"
    )

    print(
        "[SERVER] http://localhost:5000"
    )

    print()

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

    finally:

        try:

            observer.stop()

            observer.join(
                timeout=5
            )

        except Exception as error:

            print(
                "[SERVER] Ошибка остановки "
                f"watchdog: {error}"
            )


# ============================================================
# ENTRY POINT
# ============================================================
# ============================================================
# API ДЛЯ MAIN.JS
# ============================================================

@app.route("/api/shipment", methods=["GET"])
def api_shipment():
    """
    Поиск отправления по ШПИ.
    Пример:
        /api/shipment?shpi=123456789
    """

    shpi = request.args.get("shpi", "").strip()

    if not shpi:
        return jsonify({
            "success": False,
            "error": "Не указан ШПИ",
            "shipment": None,
        }), 400

    conn = get_db_connection()

    try:
        cur = conn.cursor()

        cur.execute(
            """
            SELECT *
            FROM shipments
            WHERE shpi = ?
            LIMIT 1
            """,
            (shpi,),
        )

        row = cur.fetchone()

        if row is None:
            return jsonify({
                "success": True,
                "found": False,
                "shipment": None,
            })

        return jsonify({
            "success": True,
            "found": True,
            "shipment": dict(row),
        })

    finally:
        conn.close()


@app.route("/api/internal-number", methods=["GET"])
def api_internal_number():
    number = request.args.get(
        "number",
        "",
    ).strip()

    if not number:
        return jsonify({
            "success": False,
            "error": "Не указан внутренний номер",
            "shipments": [],
            "count": 0,
        }), 400

    normalized_number = normalize_internal_number(number)

    if not normalized_number:
        return jsonify({
            "success": False,
            "error": "Не указан внутренний номер",
            "shipments": [],
            "count": 0,
        }), 400

    conn = get_db_connection()

    try:
        cur = conn.cursor()

        cur.execute(
            """
            SELECT *
            FROM shipments
            WHERE internal_number_normalized = ?
            ORDER BY id DESC
            """,
            (normalized_number,),
        )

        rows = cur.fetchall()

        shipments = [dict(row) for row in rows]

        if not shipments:
            return jsonify({
                "success": True,
                "found": False,
                "shipments": [],
                "count": 0,
                "message": "Отправления с таким внутренним номером не найдены",
            })

        return jsonify({
            "success": True,
            "found": True,
            "shipments": shipments,
            "count": len(shipments),
            "message": f"Найдено отправлений: {len(shipments)}",
        })

    finally:
        conn.close()


@app.route("/api/stats", methods=["GET"])
def api_stats():
    """
    Статистика отправлений.
    """

    conn = get_db_connection()

    try:
        cur = conn.cursor()

        # Общее количество

        cur.execute(
            """
            SELECT COUNT(*) AS total
            FROM shipments
            """
        )

        total_row = cur.fetchone()

        total = (
            int(total_row["total"])
            if total_row
            else 0
        )

        # Количество с ШПИ

        try:

            cur.execute(
                """
                SELECT COUNT(*) AS count
                FROM shipments
                WHERE shpi IS NOT NULL
                  AND TRIM(shpi) != ''
                """
            )

            shpi_row = cur.fetchone()

            with_shpi = (
                int(shpi_row["count"])
                if shpi_row
                else 0
            )

        except Exception:

            with_shpi = 0

        # Последняя загрузка

        last_uploaded = None

        try:

            cur.execute(
                """
                SELECT uploaded_at
                FROM shipments
                ORDER BY uploaded_at DESC
                LIMIT 1
                """
            )

            last_row = cur.fetchone()

            if last_row:

                last_uploaded = (
                    last_row["uploaded_at"]
                )

        except Exception:

            pass

        return jsonify({

            "success": True,

            "total": total,

            "with_shpi": with_shpi,

            "without_shpi": (
                max(
                    0,
                    total - with_shpi,
                )
            ),

            "last_uploaded": (
                last_uploaded
            ),

        })

    finally:
        conn.close()
if __name__ == "__main__":

    main()
