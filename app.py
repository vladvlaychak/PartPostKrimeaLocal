from flask import Flask, render_template, request, jsonify, flash, redirect, url_for
from waitress import serve
import os

from config import ALLOWED_SORT_FIELDS, UPLOAD_FOLDER
from db import init_db, get_db_connection
from watchdog_handler import start_watchdog

app = Flask(__name__)
app.secret_key = "supersecretkey_change_in_production"


@app.route("/")
def index():
    # Пагинация
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 50, type=int)  # по умолчанию 50
    offset = (page - 1) * per_page

    # Поиск и флаги полей
    search = request.args.get("search", "").strip()
    q_shpi = request.args.get("q_shpi") is not None
    q_recipient = request.args.get("q_recipient") is not None
    q_address = request.args.get("q_address") is not None
    q_comment = request.args.get("q_comment") is not None

    # Даты
    date_from = request.args.get("dateFrom", "").strip()
    date_to = request.args.get("dateTo", "").strip()

    # Сортировка (если нужна)
    sort_by = request.args.get("sortBy", "id")
    order = request.args.get("order", "desc").lower()
    if sort_by not in ALLOWED_SORT_FIELDS:
        sort_by = "id"
    order_norm = "DESC" if order == "desc" else "ASC"

    conn = get_db_connection()
    cur = conn.cursor()

    base_query = "SELECT * FROM shipments"
    where_clauses = []
    params = []

    # Поиск по выбранным полям
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

        if fields_to_search:
            where_clauses.append("(" + " OR ".join(fields_to_search) + ")")

    # Фильтр по датам
    if date_from:
        where_clauses.append("uploaded_at >= ?")
        params.append(date_from)
    if date_to:
        where_clauses.append("uploaded_at <= ?")
        params.append(f"{date_to} 23:59:59")

    where = " WHERE " + " AND ".join(where_clauses) if where_clauses else ""

    # Считаем общее количество записей
    count_query = f"SELECT COUNT(*) AS total FROM shipments{where}"
    cur.execute(count_query, params)
    total = cur.fetchone()["total"]

    # Запрос с пагинацией и сортировкой
    query = (
        f"{base_query}{where} ORDER BY {sort_by} {order_norm} LIMIT ? OFFSET ?"
    )
    query_params = params + [per_page, offset]
    cur.execute(query, query_params)
    rows = cur.fetchall()
    conn.close()

    shipments = [dict(row) for row in rows]
    total_pages = max(1, (total + per_page - 1) // per_page)

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
    return render_template("UploadPage.html")


@app.route("/upload", methods=["POST"])
def upload_file():
    from tempfile import NamedTemporaryFile
    from excel_processor import process_xlsx_file
    import os

    if "file" not in request.files:
        flash("Файл не выбран")
        return redirect(url_for("index"))

    file = request.files["file"]
    if file.filename == "":
        flash("Пустое имя файла")
        return redirect(url_for("index"))

    if not file.filename.lower().endswith((".xlsx", ".xls")):
        flash("Поддерживаются только файлы .xlsx и .xls")
        return redirect(url_for("index"))

    with NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1]) as tmp:
        temp_path = tmp.name
        file.save(temp_path)

    success, msg = process_xlsx_file(temp_path)

    if success:
        flash(f"✅ Готово! {msg}")
    else:
        flash(f"❌ Ошибка: {msg}")

    if os.path.exists(temp_path):
        os.remove(temp_path)

    return redirect(url_for("index"))


if __name__ == "__main__":
    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER)
        print(f"[INIT] Создана папка для загрузки файлов: {UPLOAD_FOLDER}")

    init_db()
    observer = start_watchdog(UPLOAD_FOLDER)

    try:
        serve(app, host="0.0.0.0", port=5000, threads=8)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
