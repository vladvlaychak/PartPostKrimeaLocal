import os
import sys

def resource_path(relative_path):
    """ Получает абсолютный путь к ресурсу, работает для dev и для PyInstaller """
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

DB_PATH = resource_path("data.db")
UPLOAD_FOLDER = resource_path("uploads")

ALLOWED_SORT_FIELDS = {
    "shpi", "mass", "shipping_cost", "recipient",
    "phone", "index_code", "address", "internal_number", "comment", "id", "uploaded_at"
}

FIELD_MAP = {
    "shpi": ["шпи"],
    "mass": ["масса"],
    "shipping_cost": ["стоимость", "цена"],
    "recipient": ["получатель"],
    "phone": ["телефон", "номер"],
    "index_code": ["индекс"],
    "address": ["адрес"],
    "internal_number": ["внутр", "внутренний", "вн"],
    "comment": ["комментарий", "коммент"]
}
