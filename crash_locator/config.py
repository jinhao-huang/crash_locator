from pathlib import Path
import os
from dotenv import load_dotenv
from datetime import datetime
import logging.config

load_dotenv()


class Config:
    ROOT_DIR: Path = Path.cwd()
    DATA_DIR: Path = ROOT_DIR / "Data"

    RESULT_DIR: Path = DATA_DIR / "results" / datetime.now().strftime("%Y%m%d-%H%M%S")
    RESULT_LOG_FILE_PATH: Path = RESULT_DIR / "app.log"

    CRASH_REPORTS_DIR: Path = DATA_DIR / "crash_reports" / "all-0119"

    DEBUG: bool = os.environ.get("DEBUG", "false").lower() == "true"
    DEBUG_CRASH_REPORT_DIR: Path = Path(os.environ.get("DEBUG_CRASH_REPORT_DIR"))
    DEBUG_PRE_CHECK_REPORT_DIR: Path = Path(
        os.environ.get("DEBUG_PRE_CHECK_REPORT_DIR")
    )

    PRE_CHECK_DIR: Path = DATA_DIR / "pre_check"
    PRE_CHECK_REPORTS_DIR: Path = PRE_CHECK_DIR / "reports"
    PRE_CHECK_LOG_FILE_PATH: Path = PRE_CHECK_DIR / "pre_check.log"
    PRE_CHECK_REPORT_INFO_NAME: str = "report_info.json"
    PRE_CHECK_STATISTIC_PATH: Path = PRE_CHECK_DIR / "statistic.json"

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


def setup_logging(log_file_path: Path):
    if not log_file_path.parent.exists():
        log_file_path.parent.mkdir(parents=True, exist_ok=True)

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
                    "format": "[%(asctime)s][%(filename)s][%(levelname)s] %(message)s",
                    # Optional: asctime format
                    "datefmt": "%y-%m-%d %H:%M:%S",
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
            # Just a standalone kwarg for the root logger
            "root": {"level": "DEBUG", "handlers": ["console", "file"]},
            "disable_existing_loggers": False,
        }
    )
