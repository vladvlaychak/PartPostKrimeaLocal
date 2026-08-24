from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from excel_processor import process_xlsx_file


# ------------------------------------------------------------
# Настройки
# ------------------------------------------------------------

EXCEL_EXTENSIONS = {".xlsx", ".xls"}

# Сколько секунд ждать после последнего изменения файла
# перед началом обработки.
PROCESS_DELAY = 2.0

# Максимальное время ожидания, пока файл перестанет изменяться.
FILE_READY_TIMEOUT = 60.0

# Интервал проверки готовности файла.
FILE_READY_CHECK_INTERVAL = 0.5

# Количество одинаковых проверок размера файла,
# необходимых для признания файла стабильным.
STABLE_CHECKS_REQUIRED = 3


class XlsxUploadHandler(FileSystemEventHandler):
    """
    Обработчик новых Excel-файлов в папке uploads.

    Основные особенности:
    - игнорирует не-Excel файлы;
    - не обрабатывает директории;
    - реагирует на создание и перемещение файла;
    - ждёт окончания копирования файла;
    - предотвращает повторную параллельную обработку;
    - повторно запускает таймер при новых событиях изменения.
    """

    def __init__(
        self,
        upload_folder: str | os.PathLike[str],
        process_delay: float = PROCESS_DELAY,
    ) -> None:
        super().__init__()

        self.upload_folder = Path(upload_folder).resolve()
        self.process_delay = process_delay

        self._lock = threading.RLock()

        # Файлы, которые сейчас обрабатываются.
        self._processing_files: set[str] = set()

        # Файлы, которые уже успешно обработаны.
        self._processed_files: set[str] = set()

        # Таймеры отложенной обработки.
        self._timers: dict[str, threading.Timer] = {}

        # Последнее время события для файла.
        self._last_event_time: dict[str, float] = {}

    # --------------------------------------------------------
    # Вспомогательные методы
    # --------------------------------------------------------

    @staticmethod
    def _normalize_path(file_path: str | os.PathLike[str]) -> str:
        """
        Возвращает нормализованный абсолютный путь.
        """

        return os.path.normcase(
            os.path.abspath(
                os.path.normpath(
                    str(file_path)
                )
            )
        )

    @staticmethod
    def _is_excel_file(file_path: str | os.PathLike[str]) -> bool:
        """
        Проверяет, является ли файл Excel-файлом.
        """

        return Path(file_path).suffix.lower() in EXCEL_EXTENSIONS

    def _schedule_processing(
        self,
        file_path: str | os.PathLike[str],
    ) -> None:
        """
        Планирует обработку файла.

        Если во время ожидания приходит новое событие,
        старый таймер отменяется и запускается новый.
        Это позволяет дождаться полного окончания копирования.
        """

        normalized_path = self._normalize_path(file_path)

        with self._lock:
            if normalized_path in self._processed_files:
                return

            self._last_event_time[normalized_path] = time.time()

            old_timer = self._timers.get(normalized_path)

            if old_timer is not None:
                old_timer.cancel()

            timer = threading.Timer(
                self.process_delay,
                self._process_file_safe,
                args=(normalized_path,),
            )

            timer.daemon = True

            self._timers[normalized_path] = timer

            timer.start()

        print(
            f"[WATCHDOG] Файл обнаружен, "
            f"ожидание завершения копирования: {normalized_path}"
        )

    def _wait_until_file_ready(
        self,
        file_path: str,
    ) -> bool:
        """
        Ожидает, пока файл:
        - появится на диске;
        - перестанет изменять размер;
        - будет доступен для чтения.

        Возвращает True, если файл готов к обработке.
        """

        start_time = time.time()

        previous_size: int | None = None
        stable_checks = 0

        while time.time() - start_time < FILE_READY_TIMEOUT:
            try:
                if not os.path.isfile(file_path):
                    time.sleep(FILE_READY_CHECK_INTERVAL)
                    continue

                current_size = os.path.getsize(file_path)

                # Пустой файл ещё может копироваться.
                if current_size <= 0:
                    stable_checks = 0
                    previous_size = current_size

                    time.sleep(FILE_READY_CHECK_INTERVAL)
                    continue

                # Проверяем, изменяется ли размер файла.
                if previous_size == current_size:
                    stable_checks += 1
                else:
                    stable_checks = 0

                previous_size = current_size

                # Пытаемся открыть файл на чтение.
                try:
                    with open(file_path, "rb"):
                        pass
                except (PermissionError, OSError):
                    stable_checks = 0

                    time.sleep(FILE_READY_CHECK_INTERVAL)
                    continue

                if stable_checks >= STABLE_CHECKS_REQUIRED:
                    return True

            except FileNotFoundError:
                stable_checks = 0
                previous_size = None

            except PermissionError:
                stable_checks = 0

            except OSError as error:
                print(
                    f"[WATCHDOG] Ошибка проверки файла "
                    f"{file_path}: {error}"
                )

                stable_checks = 0

            time.sleep(FILE_READY_CHECK_INTERVAL)

        return False

    def _process_file_safe(
        self,
        file_path: str,
    ) -> None:
        """
        Безопасно запускает обработку Excel-файла.
        """

        with self._lock:
            self._timers.pop(file_path, None)

            if file_path in self._processed_files:
                return

            if file_path in self._processing_files:
                return

            self._processing_files.add(file_path)

        try:
            print(
                f"[WATCHDOG] Проверка готовности файла: "
                f"{file_path}"
            )

            if not self._wait_until_file_ready(file_path):
                print(
                    f"[WATCHDOG] Файл не стал доступен "
                    f"за {FILE_READY_TIMEOUT:.0f} сек.: "
                    f"{file_path}"
                )
                return

            print(
                f"[WATCHDOG] Начало обработки файла: "
                f"{file_path}"
            )

            success, message = process_xlsx_file(file_path)

            if success:
                with self._lock:
                    self._processed_files.add(file_path)

                print(
                    f"[WATCHDOG] Файл успешно обработан: "
                    f"{file_path}"
                )

                print(
                    f"[WATCHDOG] Результат: {message}"
                )

            else:
                print(
                    f"[WATCHDOG] Не удалось обработать файл "
                    f"{file_path}: {message}"
                )

        except PermissionError as error:
            print(
                f"[WATCHDOG] Ошибка доступа к файлу "
                f"{file_path}: {error}"
            )

        except FileNotFoundError:
            print(
                f"[WATCHDOG] Файл был удалён до обработки: "
                f"{file_path}"
            )

        except Exception as error:
            print(
                f"[WATCHDOG] Критическая ошибка при обработке "
                f"{file_path}: {error}"
            )

        finally:
            with self._lock:
                self._processing_files.discard(file_path)

                # Очищаем устаревшую информацию о событии.
                self._last_event_time.pop(file_path, None)

    # --------------------------------------------------------
    # События watchdog
    # --------------------------------------------------------

    def on_created(
        self,
        event: FileSystemEvent,
    ) -> None:
        """
        Новый файл появился в папке.
        """

        if event.is_directory:
            return

        if not self._is_excel_file(event.src_path):
            return

        self._schedule_processing(event.src_path)

    def on_modified(
        self,
        event: FileSystemEvent,
    ) -> None:
        """
        Файл изменился.

        Это важно при копировании больших файлов:
        on_created может произойти раньше, чем копирование
        будет полностью завершено.
        """

        if event.is_directory:
            return

        if not self._is_excel_file(event.src_path):
            return

        normalized_path = self._normalize_path(event.src_path)

        with self._lock:
            if normalized_path in self._processed_files:
                return

            if normalized_path in self._processing_files:
                return

        self._schedule_processing(event.src_path)

    def on_moved(
        self,
        event: FileSystemEvent,
    ) -> None:
        """
        Файл был перемещён в uploads.

        Некоторые программы сначала создают временный файл,
        а после завершения сохранения переименовывают его.
        """

        if event.is_directory:
            return

        destination_path = getattr(
            event,
            "dest_path",
            None,
        )

        if not destination_path:
            return

        if not self._is_excel_file(destination_path):
            return

        self._schedule_processing(destination_path)

    def on_deleted(
        self,
        event: FileSystemEvent,
    ) -> None:
        """
        Очищает внутренние данные при удалении файла.
        """

        if event.is_directory:
            return

        normalized_path = self._normalize_path(event.src_path)

        with self._lock:
            timer = self._timers.pop(
                normalized_path,
                None,
            )

            if timer is not None:
                timer.cancel()

            self._processed_files.discard(normalized_path)
            self._processing_files.discard(normalized_path)
            self._last_event_time.pop(
                normalized_path,
                None,
            )

    # --------------------------------------------------------
    # Завершение работы
    # --------------------------------------------------------

    def stop(self) -> None:
        """
        Отменяет все ожидающие таймеры.
        """

        with self._lock:
            for timer in self._timers.values():
                timer.cancel()

            self._timers.clear()


def start_watchdog(
    upload_folder: str | os.PathLike[str],
) -> Observer:
    """
    Запускает мониторинг папки uploads.

    Перед запуском папка автоматически создаётся,
    если она отсутствует.

    Возвращает объект Observer.
    """

    upload_path = Path(upload_folder).resolve()

    upload_path.mkdir(
        parents=True,
        exist_ok=True,
    )

    event_handler = XlsxUploadHandler(upload_path)

    observer = Observer()

    observer.schedule(
        event_handler,
        path=str(upload_path),
        recursive=False,
    )

    observer.start()

    print(
        f"[WATCHDOG] Мониторинг запущен: "
        f"{upload_path}"
    )

    return observer
