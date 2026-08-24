from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from excel_processor import process_xlsx_file
from upload_status import update_job_by_path


EXCEL_EXTENSIONS = {
    ".xlsx",
    ".xls",
}


PROCESS_DELAY = 2.0

FILE_READY_TIMEOUT = 120.0

FILE_READY_CHECK_INTERVAL = 0.5

STABLE_CHECKS_REQUIRED = 3


class XlsxUploadHandler(FileSystemEventHandler):

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
            threading.Timer
        ] = {}

        self._lock = threading.RLock()

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

    def _schedule_processing(
        self,
        file_path: str,
    ) -> None:

        normalized_path = (
            self._normalize_path(file_path)
        )

        with self._lock:

            if (
                normalized_path
                in self._processed_files
            ):
                return

            old_timer = self._timers.get(
                normalized_path
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
            "Файл обнаружен. Ожидание окончания копирования...",
        )

        print(
            "[WATCHDOG] Файл обнаружен: "
            f"{normalized_path}"
        )

    def _wait_until_ready(
        self,
        file_path: str,
    ) -> bool:

        started = time.time()

        previous_size: int | None = None

        stable_checks = 0

        while (
            time.time() - started
            < FILE_READY_TIMEOUT
        ):

            try:

                if not os.path.isfile(
                    file_path
                ):

                    time.sleep(
                        FILE_READY_CHECK_INTERVAL
                    )

                    continue

                current_size = (
                    os.path.getsize(
                        file_path
                    )
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

                if (
                    previous_size
                    == current_size
                ):

                    stable_checks += 1

                else:

                    stable_checks = 0

                previous_size = current_size

                try:

                    with open(
                        file_path,
                        "rb",
                    ):
                        pass

                except (
                    PermissionError,
                    OSError,
                ):

                    stable_checks = 0

                    time.sleep(
                        FILE_READY_CHECK_INTERVAL
                    )

                    continue

                if (
                    stable_checks
                    >= STABLE_CHECKS_REQUIRED
                ):

                    return True

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

        return False

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

            update_job_by_path(
                file_path,
                "waiting",
                "Проверка готовности файла...",
            )

            if not self._wait_until_ready(
                file_path
            ):

                message = (
                    "Файл не стал доступен "
                    f"за {FILE_READY_TIMEOUT:.0f} сек."
                )

                update_job_by_path(
                    file_path,
                    "error",
                    message,
                )

                print(
                    "[WATCHDOG] "
                    f"{message} {file_path}"
                )

                return

            update_job_by_path(
                file_path,
                "processing",
                "Файл обрабатывается...",
            )

            print(
                "[WATCHDOG] Начало обработки: "
                f"{file_path}"
            )

            success, message = (
                process_xlsx_file(
                    file_path
                )
            )

            if success:

                with self._lock:

                    self._processed_files.add(
                        file_path
                    )

                update_job_by_path(
                    file_path,
                    "completed",
                    message,
                )

                print(
                    "[WATCHDOG] Успешно обработан: "
                    f"{file_path}"
                )

            else:

                update_job_by_path(
                    file_path,
                    "error",
                    message,
                )

                print(
                    "[WATCHDOG] Ошибка обработки: "
                    f"{message}"
                )

        except PermissionError as error:

            message = (
                f"Нет доступа к файлу: {error}"
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

        except FileNotFoundError:

            message = (
                "Файл был удалён до завершения обработки."
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

        except Exception as error:

            message = (
                f"Критическая ошибка: {error}"
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

        finally:

            with self._lock:

                self._processing_files.discard(
                    file_path
                )

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

            timer = self._timers.pop(
                normalized_path,
                None,
            )

            if timer:
                timer.cancel()

            self._processed_files.discard(
                normalized_path
            )

            self._processing_files.discard(
                normalized_path
            )

    def stop(self) -> None:

        with self._lock:

            for timer in self._timers.values():
                timer.cancel()

            self._timers.clear()


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

    event_handler = XlsxUploadHandler(
        upload_path
    )

    observer = Observer()

    observer.schedule(
        event_handler,
        path=str(upload_path),
        recursive=False,
    )

    observer.start()

    print(
        "[WATCHDOG] Мониторинг запущен: "
        f"{upload_path}"
    )

    return observer
