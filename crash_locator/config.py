from pathlib import Path
import os
import json
from dotenv import load_dotenv
from datetime import datetime
import logging.config
import threading
from crash_locator.exceptions import LoggerNotFoundException
from crash_locator.my_types import RunStatistic

load_dotenv()


class Config:
    ROOT_DIR: Path = Path.cwd()
    DATA_DIR: Path = ROOT_DIR / "Data"

    OPENAI_BASE_URL: str = os.environ.get("OPENAI_BASE_URL")
    OPENAI_API_KEY: str = os.environ.get("OPENAI_API_KEY")
    OPENAI_MODEL: str = os.environ.get("OPENAI_MODEL")

    # Crash reports directory
    CRASH_REPORTS_DIR: Path = DATA_DIR / "crash_reports" / "all-0119"

    @staticmethod
    def CRASH_REPORT_PATH(report_name: str) -> Path:
        return Config.CRASH_REPORTS_DIR / report_name / f"{report_name}.json"

    # Pre_check directory
    PRE_CHECK_DIR: Path = DATA_DIR / "pre_check"
    PRE_CHECK_STATISTIC_PATH: Path = PRE_CHECK_DIR / "statistic.json"

    PRE_CHECK_REPORTS_DIR: Path = PRE_CHECK_DIR / "reports"

    @staticmethod
    def PRE_CHECK_REPORT_INFO_PATH(report_name: str) -> Path:
        return Config.PRE_CHECK_REPORTS_DIR / report_name / "report_info.json"

    # Result directory
    RESULT_DIR: Path = DATA_DIR / "results" / "20250422"
    RESULT_STATISTIC_PATH: Path = RESULT_DIR / "statistic.json"

    @staticmethod
    def RESULT_REPORT_DIR(report_name: str) -> Path:
        return Config.RESULT_DIR / "reports" / report_name

    @staticmethod
    def RESULT_REPORT_FILTER_DIR(report_name: str) -> Path:
        return Config.RESULT_REPORT_DIR(report_name) / "filter"

    MAX_WORKERS: int = int(os.environ.get("MAX_WORKERS", "4"))
    RETRY_FAILED_REPORTS: bool = True

    DEBUG: bool = os.environ.get("DEBUG", "false").lower() == "true"
    DEBUG_CRASH_REPORT_DIR: Path = Path(os.environ.get("DEBUG_CRASH_REPORT_DIR"))
    DEBUG_PRE_CHECK_REPORT_DIR: Path = Path(
        os.environ.get("DEBUG_PRE_CHECK_REPORT_DIR")
    )

    APPLICATION_CODE_DIR: Path = DATA_DIR / "application_source_code"

    def APPLICATION_CODE_PATH(apk_name: str) -> Path:
        return Config.APPLICATION_CODE_DIR / apk_name / "sources"

    ANDROID_CG_PATH = lambda v: f"Data/AndroidCG/android{v}/android{v}_cg.txt"
    APK_CG_PATH = lambda apk_name: f"Data/ApkCG/{apk_name}/{apk_name}_cg.txt"
    ANDROID_CG_CALLED_CACHE_PATH = (
        lambda v,
        hashed_signature: f"Data/CgCache/AndroidCG_called_cache/android_{v}/{hashed_signature}.json"
    )
    ANDROID_CG_CALLER_CACHE_PATH = (
        lambda v,
        hashed_signature: f"Data/CgCache/AndroidCG_caller_cache/android_{v}/{hashed_signature}.json"
    )
    APK_CG_CALLED_CACHE_PATH = (
        lambda apk_name,
        hashed_signature: f"Data/CgCache/ApkCG_called_cache/{apk_name}/{hashed_signature}.json"
    )
    APK_CG_CALLER_CACHE_PATH = (
        lambda apk_name,
        hashed_signature: f"Data/CgCache/ApkCG_caller_cache/{apk_name}/{hashed_signature}.json"
    )


def setup_logging(log_file_dir: Path):
    if not log_file_dir.exists():
        log_file_dir.mkdir(parents=True, exist_ok=True)
    log_file_path = log_file_dir / "app.log"

    logging.config.dictConfig(
        {
            # Always 1. Schema versioning may be added in a future release of logging
            "version": 1,
            # "Name of formatter" : {Formatter Config Dict}
            "formatters": {
                # Formatter Name
                "standard": {
                    # class is always "logging.Formatter"
                    "class": "logging.Formatter",
                    # Optional: logging output format
                    "format": "[%(asctime)s] [%(filename)s] [%(levelname)s] %(message)s",
                    # Optional: asctime format
                    "datefmt": "%Y-%m-%d %H:%M:%S",
                }
            },
            # Handlers use the formatter names declared above
            "handlers": {
                # Name of handler
                "console": {
                    # The class of logger. A mixture of logging.config.dictConfig() and
                    # logger class-specific keyword arguments (kwargs) are passed in here.
                    "class": "logging.StreamHandler",
                    # This is the formatter name declared above
                    "formatter": "standard",
                    "level": "INFO",
                    # The default is stderr
                    "stream": "ext://sys.stdout",
                },
                "file": {
                    "class": "logging.FileHandler",
                    "formatter": "standard",
                    "level": "DEBUG",
                    "filename": log_file_path,
                    "mode": "a",
                    "encoding": "utf-8",
                },
            },
            "loggers": {
                "crash_locator": {
                    "handlers": ["console", "file"],
                    "level": "DEBUG",
                    "propagate": False,
                },
            },
            # Just a standalone kwarg for the root logger
            "root": {"level": "DEBUG", "handlers": ["console", "file"]},
            "disable_existing_loggers": True,
        }
    )


_thread_local = threading.local()


def set_thread_logger(logger: logging.LoggerAdapter):
    global _thread_local
    setattr(_thread_local, "logger", logger)


def get_thread_logger() -> logging.LoggerAdapter:
    global _thread_local
    if hasattr(_thread_local, "logger"):
        return getattr(_thread_local, "logger")
    raise LoggerNotFoundException("Logger not found")


def clear_thread_logger():
    global _thread_local
    if hasattr(_thread_local, "logger"):
        delattr(_thread_local, "logger")


def init_statistic() -> RunStatistic:
    if Config.RESULT_STATISTIC_PATH.exists():
        with open(Config.RESULT_STATISTIC_PATH, "r") as f:
            run_statistic = RunStatistic(**json.load(f))
    else:
        run_statistic = RunStatistic(
            model_info=RunStatistic.ModelInfo(
                model_name=Config.OPENAI_MODEL,
            ),
        )
    run_statistic.set_path(Config.RESULT_STATISTIC_PATH)

    return run_statistic


run_statistic: RunStatistic = init_statistic()

exit_flag: bool = False


def set_exit_flag():
    global exit_flag
    exit_flag = True
