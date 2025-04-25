from pathlib import Path
import os
import json
from dotenv import load_dotenv
from datetime import datetime
import logging.config
from crash_locator.my_types import RunStatistic
import asyncio
import logging

load_dotenv(override=True)


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
    DEBUG_CRASH_REPORTS: list[str] = os.environ.get("DEBUG_CRASH_REPORTS", "").split(
        ","
    )
    DEBUG_PRE_CHECK_REPORTS: list[str] = os.environ.get(
        "DEBUG_PRE_CHECK_REPORTS", ""
    ).split(",")

    APPLICATION_CODE_DIR: Path = DATA_DIR / "application_source_code"

    def APPLICATION_CODE_PATH(apk_name: str) -> Path:
        return Config.APPLICATION_CODE_DIR / apk_name / "sources"

    @staticmethod
    def ANDROID_CG_PATH(v: str) -> Path:
        return Config.DATA_DIR / "AndroidCG" / f"android{v}" / f"android{v}_cg.txt"

    @staticmethod
    def APK_CG_PATH(apk_name: str) -> Path:
        return Config.DATA_DIR / "ApkCG" / apk_name / f"{apk_name}_cg.txt"

    @staticmethod
    def ANDROID_CG_CALLED_CACHE_PATH(v: str, hashed_signature: str) -> Path:
        return (
            Config.DATA_DIR
            / "CgCache"
            / "AndroidCG_called_cache"
            / f"android_{v}"
            / f"{hashed_signature}.json"
        )

    @staticmethod
    def ANDROID_CG_CALLER_CACHE_PATH(v: str, hashed_signature: str) -> Path:
        return (
            Config.DATA_DIR
            / "CgCache"
            / "AndroidCG_caller_cache"
            / f"android_{v}"
            / f"{hashed_signature}.json"
        )

    @staticmethod
    def APK_CG_CALLED_CACHE_PATH(apk_name: str, hashed_signature: str) -> Path:
        return (
            Config.DATA_DIR
            / "CgCache"
            / "ApkCG_called_cache"
            / apk_name
            / f"{hashed_signature}.json"
        )

    @staticmethod
    def APK_CG_CALLER_CACHE_PATH(apk_name: str, hashed_signature: str) -> Path:
        return (
            Config.DATA_DIR
            / "CgCache"
            / "ApkCG_caller_cache"
            / apk_name
            / f"{hashed_signature}.json"
        )


# Custom filter to add task name to log records
class TaskNameFilter(logging.Filter):
    def filter(self, record):
        try:
            task = asyncio.current_task()
        except RuntimeError:
            record.taskName = "MainThread"
        else:
            if task:
                record.taskName = task.get_name()
            else:
                record.taskName = "MainTask"

        return True


def setup_logging(log_file_dir: Path):
    if not log_file_dir.exists():
        log_file_dir.mkdir(parents=True, exist_ok=True)
    log_file_path = log_file_dir / "app.log"

    try:
        task = asyncio.current_task()
        if task:
            task.set_name("MainTask")
    except RuntimeError:
        pass

    logging.config.dictConfig(
        {
            # Always 1. Schema versioning may be added in a future release of logging
            "version": 1,
            # Add filters definition
            "filters": {
                "task_name_filter": {
                    "()": TaskNameFilter,
                }
            },
            # "Name of formatter" : {Formatter Config Dict}
            "formatters": {
                # Formatter Name
                "standard": {
                    # class is always "logging.Formatter"
                    "class": "logging.Formatter",
                    # Optional: logging output format - Added %(taskName)s and %(lineno)d
                    "format": "[%(asctime)s] [%(filename)s:%(lineno)d] [%(levelname)s] [%(taskName)s] %(message)s",
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
                    # Add the filter to the handler
                    "filters": ["task_name_filter"],
                },
                "file": {
                    "class": "logging.FileHandler",
                    "formatter": "standard",
                    "level": "DEBUG",
                    "filename": log_file_path,
                    "mode": "a",
                    "encoding": "utf-8",
                    # Add the filter to the handler
                    "filters": ["task_name_filter"],
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
