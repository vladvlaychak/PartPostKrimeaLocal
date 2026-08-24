from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from excel_processor import process_xlsx_file
from upload_status import update_job_by_path


# ============================================================
# НАСТРОЙКИ
# ============================================================

EXCEL_EXTENSIONS = {
    ".xlsx",
    ".xls",
}

# Через сколько секунд после события начинать проверку.
PROCESS_DELAY = 2.0

# Максимальное время ожидания готовности файла.
FILE_READY_TIMEOUT = 120.0

# Интервал проверки размера файла.
FILE_READY_CHECK_INTERVAL = 0.5

# Сколько раз подряд размер должен оставаться одинаковым.
STABLE_CHECKS_REQUIRED = 4


class XlsxUploadHandler(FileSystemEventHandler):
    """
    Watchdog для папки uploads.

    Схема:

        upload
           ↓
        uploads/
           ↓
        watchdog
           ↓
        проверка готовности
           ↓
        process_xlsx_file()
           ↓
        SQLite
    """

    def __init__(
        self,
        upload_folder: str | os.PathLike[str],
    ) -> None:

        super().__init__()

        self.upload_folder = Path(
            upload_folder
        ).resolve()

        self._processing_files: set[str] = set()

        self._processed_files: set[str] = set()

        self._timers: dict[
            str,
            threading.Timer,
        ] = {}

        self._lock = threading.RLock()

    # ========================================================
    # ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
    # ========================================================

    @staticmethod
    def _normalize_path(
        file_path: str | os.PathLike[str],
    ) -> str:

        return os.path.normcase(
            os.path.abspath(
                os.path.normpath(
                    str(file_path)
                )
            )
        )

    @staticmethod
    def _is_excel_file(
        file_path: str | os.PathLike[str],
    ) -> bool:

        return (
            Path(file_path)
            .suffix
            .lower()
            in EXCEL_EXTENSIONS
        )

    # ========================================================
    # ПЛАНИРОВАНИЕ ОБРАБОТКИ
    # ========================================================

    def _schedule_processing(
        self,
        file_path: str,
    ) -> None:

        normalized_path = (
            self._normalize_path(
                file_path
            )
        )

        with self._lock:

            # Уже обработан
            if (
                normalized_path
                in self._processed_files
            ):
                return

            # Уже находится в обработке
            if (
                normalized_path
                in self._processing_files
            ):
                return

            # Отменяем старый таймер
            old_timer = (
                self._timers.get(
                    normalized_path
                )
            )

            if old_timer is not None:
                old_timer.cancel()

            timer = threading.Timer(
                PROCESS_DELAY,
                self._process_file_safe,
                args=(normalized_path,),
            )

            timer.daemon = True

            self._timers[
                normalized_path
            ] = timer

            timer.start()

        update_job_by_path(
            normalized_path,
            "waiting",
            "Файл обнаружен. Ожидание окончания загрузки...",
        )

        print(
            "[WATCHDOG] Файл обнаружен: "
            f"{normalized_path}"
        )

    # ========================================================
    # ПРОВЕРКА ГОТОВНОСТИ ФАЙЛА
    # ========================================================

    def _wait_until_ready(
        self,
        file_path: str,
    ) -> tuple[bool, str]:
        """
        Ждём, пока файл полностью скопируется.

        Возвращает:

            (True, "")
            или
            (False, "текст ошибки")
        """

        started_at = time.monotonic()

        previous_size: int | None = None

        stable_checks = 0

        while (
            time.monotonic() - started_at
            < FILE_READY_TIMEOUT
        ):

            try:

                path = Path(
                    file_path
                )

                if not path.exists():

                    stable_checks = 0

                    time.sleep(
                        FILE_READY_CHECK_INTERVAL
                    )

                    continue

                if not path.is_file():

                    return (
                        False,
                        "Путь не является файлом",
                    )

                current_size = (
                    path.stat().st_size
                )

                if current_size <= 0:

                    previous_size = (
                        current_size
                    )

                    stable_checks = 0

                    time.sleep(
                        FILE_READY_CHECK_INTERVAL
                    )

                    continue

                # Размер не изменился
                if (
                    previous_size
                    == current_size
                ):

                    stable_checks += 1

                else:

                    stable_checks = 0

                previous_size = current_size

                # Проверяем возможность открыть файл
                try:

                    with open(
                        path,
                        "rb",
                    ) as file:

                        file.read(1)

                except (
                    PermissionError,
                    OSError,
                ):

                    stable_checks = 0

                    time.sleep(
                        FILE_READY_CHECK_INTERVAL
                    )

                    continue

                # Файл стабилен
                if (
                    stable_checks
                    >= STABLE_CHECKS_REQUIRED
                ):

                    return (
                        True,
                        "",
                    )

            except FileNotFoundError:

                previous_size = None

                stable_checks = 0

            except PermissionError:

                stable_checks = 0

            except OSError as error:

                print(
                    "[WATCHDOG] Ошибка проверки "
                    f"{file_path}: {error}"
                )

                stable_checks = 0

            time.sleep(
                FILE_READY_CHECK_INTERVAL
            )

        return (
            False,
            (
                "Файл не стал доступен "
                f"за {FILE_READY_TIMEOUT:.0f} секунд"
            ),
        )

    # ========================================================
    # ОБРАБОТКА
    # ========================================================

    def _process_file_safe(
        self,
        file_path: str,
    ) -> None:

        with self._lock:

            self._timers.pop(
                file_path,
                None,
            )

            if (
                file_path
                in self._processed_files
            ):
                return

            if (
                file_path
                in self._processing_files
            ):
                return

            self._processing_files.add(
                file_path
            )

        try:

            print(
                "[WATCHDOG] Проверка файла: "
                f"{file_path}"
            )

            update_job_by_path(
                file_path,
                "waiting",
                "Проверка готовности файла...",
            )

            # ------------------------------------------------
            # Ждём окончания копирования
            # ------------------------------------------------

            ready, ready_message = (
                self._wait_until_ready(
                    file_path
                )
            )

            if not ready:

                update_job_by_path(
                    file_path,
                    "error",
                    ready_message,
                )

                print(
                    "[WATCHDOG] Ошибка готовности: "
                    f"{ready_message}"
                )

                return

            # ------------------------------------------------
            # Файл готов
            # ------------------------------------------------

            update_job_by_path(
                file_path,
                "processing",
                "Файл готов. Начинается обработка...",
            )

            print(
                "[WATCHDOG] Начало обработки: "
                f"{file_path}"
            )

            # ------------------------------------------------
            # Передаём существующему processor
            # ------------------------------------------------

            result = process_xlsx_file(
                file_path
            )

            # ------------------------------------------------
            # Проверяем результат processor
            # ------------------------------------------------

            if (
                not isinstance(
                    result,
                    tuple,
                )
                or len(result) != 2
            ):

                message = (
                    "excel_processor.py "
                    "вернул неправильный результат. "
                    "Ожидалось: (success, message)"
                )

                update_job_by_path(
                    file_path,
                    "error",
                    message,
                )

                print(
                    "[WATCHDOG] "
                    f"{message}"
                )

                return

            success, message = result

            message = str(
                message
                or ""
            )

            # ------------------------------------------------
            # УСПЕХ
            # ------------------------------------------------

            if success:

                with self._lock:

                    self._processed_files.add(
                        file_path
                    )

                update_job_by_path(
                    file_path,
                    "completed",
                    message
                    or "Файл успешно обработан",
                )

                print(
                    "[WATCHDOG] "
                    "✓ Успешно обработан: "
                    f"{file_path}"
                )

                print(
                    "[WATCHDOG] Результат: "
                    f"{message}"
                )

            # ------------------------------------------------
            # ОШИБКА ОБРАБОТКИ
            # ------------------------------------------------

            else:

                update_job_by_path(
                    file_path,
                    "error",
                    message
                    or "excel_processor вернул ошибку",
                )

                print(
                    "[WATCHDOG] "
                    "✗ Ошибка обработки: "
                    f"{file_path}"
                )

                print(
                    "[WATCHDOG] Причина: "
                    f"{message}"
                )

        # ====================================================
        # ОШИБКИ ДОСТУПА
        # ====================================================

        except PermissionError as error:

            message = (
                "Нет доступа к файлу: "
                f"{error}"
            )

            update_job_by_path(
                file_path,
                "error",
                message,
            )

            print(
                "[WATCHDOG] ✗ "
                f"{message}"
            )

        # ====================================================
        # ФАЙЛ УДАЛЁН
        # ====================================================

        except FileNotFoundError as error:

            message = (
                "Файл был удалён "
                "до завершения обработки: "
                f"{error}"
            )

            update_job_by_path(
                file_path,
                "error",
                message,
            )

            print(
                "[WATCHDOG] ✗ "
                f"{message}"
            )

        # ====================================================
        # ЛЮБАЯ ДРУГАЯ ОШИБКА
        # ====================================================

        except Exception as error:

            message = (
                f"{type(error).__name__}: "
                f"{error}"
            )

            update_job_by_path(
                file_path,
                "error",
                message,
            )

            print(
                "[WATCHDOG] ✗ Критическая ошибка"
            )

            print(
                "[WATCHDOG] Файл: "
                f"{file_path}"
            )

            print(
                "[WATCHDOG] Ошибка: "
                f"{message}"
            )

        finally:

            with self._lock:

                self._processing_files.discard(
                    file_path
                )

    # ========================================================
    # СОЗДАНИЕ ФАЙЛА
    # ========================================================

    def on_created(
        self,
        event,
    ) -> None:

        if event.is_directory:
            return

        if not self._is_excel_file(
            event.src_path
        ):
            return

        self._schedule_processing(
            event.src_path
        )

    # ========================================================
    # ИЗМЕНЕНИЕ ФАЙЛА
    # ========================================================

    def on_modified(
        self,
        event,
    ) -> None:

        if event.is_directory:
            return

        if not self._is_excel_file(
            event.src_path
        ):
            return

        normalized_path = (
            self._normalize_path(
                event.src_path
            )
        )

        with self._lock:

            if (
                normalized_path
                in self._processed_files
            ):
                return

            if (
                normalized_path
                in self._processing_files
            ):
                return

        self._schedule_processing(
            event.src_path
        )

    # ========================================================
    # ПЕРЕМЕЩЕНИЕ ФАЙЛА
    # ========================================================

    def on_moved(
        self,
        event,
    ) -> None:

        if event.is_directory:
            return

        destination = getattr(
            event,
            "dest_path",
            None,
        )

        if not destination:
            return

        if not self._is_excel_file(
            destination
        ):
            return

        self._schedule_processing(
            destination
        )

    # ========================================================
    # УДАЛЕНИЕ ФАЙЛА
    # ========================================================

    def on_deleted(
        self,
        event,
    ) -> None:

        if event.is_directory:
            return

        normalized_path = (
            self._normalize_path(
                event.src_path
            )
        )

        with self._lock:

            timer = (
                self._timers.pop(
                    normalized_path,
                    None,
                )
            )

            if timer is not None:
                timer.cancel()

            self._processing_files.discard(
                normalized_path
            )

            # ВАЖНО:
            #
            # Не удаляем processed_files.
            #
            # excel_processor.py сам удаляет
            # успешно обработанный Excel.
            #
            # Если удалить запись здесь,
            # последующие события могут
            # снова поставить файл в очередь.

    # ========================================================
    # ОСТАНОВКА
    # ========================================================

    def stop(self) -> None:

        with self._lock:

            timers = list(
                self._timers.values()
            )

            self._timers.clear()

        for timer in timers:

            try:
                timer.cancel()
            except Exception:
                pass


# ============================================================
# ЗАПУСК WATCHDOG
# ============================================================

def start_watchdog(
    upload_folder: str | os.PathLike[str],
) -> Observer:

    upload_path = Path(
        upload_folder
    ).resolve()

    upload_path.mkdir(
        parents=True,
        exist_ok=True,
    )

    event_handler = (
        XlsxUploadHandler(
            upload_path
        )
    )

    observer = Observer()

    observer.schedule(
        event_handler,
        path=str(upload_path),
        recursive=False,
    )

    observer.start()

    print(
        "[WATCHDOG] =================================="
    )

    print(
        "[WATCHDOG] Мониторинг запущен"
    )

    print(
        "[WATCHDOG] Папка: "
        f"{upload_path}"
    )

    print(
        "[WATCHDOG] Поддерживаемые файлы: "
        ".xlsx, .xls"
    )

    print(
        "[WATCHDOG] =================================="
    )

    return observer
