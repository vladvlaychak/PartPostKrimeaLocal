import time
import os
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from excel_processor import process_xlsx_file

class XlsxUploadHandler(FileSystemEventHandler):
    def __init__(self, upload_folder):
        self.upload_folder = upload_folder
        self._processed_files = set()
        self._lock_time = {}

    def on_created(self, event):
        if event.is_directory:
            return

        file_path = event.src_path

        if not file_path.lower().endswith(('.xlsx', '.xls')):
            return

        now = time.time()
        if file_path in self._processed_files:
            return
        if file_path in self._lock_time and now - self._lock_time[file_path] < 2:
            return
        self._lock_time[file_path] = now

        print(f"[WATCHDOG] Обнаружен файл: {file_path}")

        try:
            success, msg = process_xlsx_file(file_path)
            if success:
                self._processed_files.add(file_path)
                cutoff = now - 3600
                self._lock_time = {k: v for k, v in self._lock_time.items() if v > cutoff}
            else:
                print(f"[WATCHDOG] Не удалось обработать: {msg}")
        except Exception as e:
            print(f"[WATCHDOG] Критическая ошибка: {e}")


def start_watchdog(upload_folder):
    observer = Observer()
    event_handler = XlsxUploadHandler(upload_folder)
    observer.schedule(event_handler, path=upload_folder, recursive=False)
    observer.start()
    print(f"[WATCHDOG] Мониторинг запущен: {upload_folder}")
    return observer
