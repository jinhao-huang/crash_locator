from pathlib import Path
import json
from datetime import datetime
import logging.config
from crash_locator.types.llm import APIType, ReasoningEffort
from crash_locator.my_types import RunStatistic
import asyncio
import logging
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from cachier import set_default_params
from typing import Optional, Dict, Any


class Config(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="crash_locator_", env_file=".env", cli_parse_args=True
    )

    preset: Optional[str] = None

    enable_extract_constraint: bool
    enable_notes: bool
    enable_candidate_reason: bool
    enable_candidate_correction: bool
    reasoning_effort: ReasoningEffort | None = None

    root_dir: Path = Path(__file__).parent.parent

    @property
    def data_dir(self) -> Path:
        return self.root_dir / "Data"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    openai_base_url: str
    openai_api_key: str
    openai_model: str
    openai_api_type: APIType = APIType.RESPONSE

    # Pre_check directory
    @property
    def pre_check_dir(self) -> Path:
        return self.data_dir / "pre_check"

    @property
    def pre_check_statistic_path(self) -> Path:
        return self.pre_check_dir / "statistic.json"

    @property
    def pre_check_reports_dir(self) -> Path:
        return self.pre_check_dir / "reports"

    def pre_check_report_info_path(self, report_name: str) -> Path:
        return self.pre_check_reports_dir / report_name / "report_info.json"

    # Result directory
    result_dir_name: str = Field(
        default_factory=lambda: datetime.now().strftime("%Y%m%d")
    )

    @property
    def result_dir(self) -> Path:
        return self.data_dir / "results" / self.result_dir_name

    @property
    def result_statistic_path(self) -> Path:
        return self.result_dir / "statistic.json"

    def result_report_dir(self, report_name: str) -> Path:
        return self.result_dir / "reports" / report_name

    def result_report_filter_dir(self, report_name: str) -> Path:
        return self.result_report_dir(report_name) / "filter"

    def result_report_constraint_dir(self, report_name: str) -> Path:
        return self.result_report_dir(report_name) / "constraint"

    max_workers: int = 4
    retry_failed_reports: bool = True

    debug: bool = False
    debug_crash_reports: list[str] = Field(default_factory=list)
    debug_pre_check_reports: list[str] = Field(default_factory=list)

    resources_dir_name: str = "resources"

    @property
    def resources_dir(self) -> Path:
        return self.data_dir / self.resources_dir_name

    # Crash reports directory
    crash_reports_dir_name: str = "all-0427"

    @property
    def crash_reports_dir(self) -> Path:
        return self.resources_dir / "crash_reports" / self.crash_reports_dir_name

    def crash_report_path(self, report_name: str) -> Path:
        return self.crash_reports_dir / report_name / f"{report_name}.json"

    def android_code_dir(self, v: str) -> list[Path]:
        base_dir = (
            self.resources_dir
            / "android_code"
            / f"platform_frameworks_base-android-{v}_r1"
        )
        return [
            base_dir / "core" / "java",
            base_dir / "location" / "java",
        ]

    def android_support_code_dir(self) -> Path:
        return self.resources_dir / "android_support_code" / "src"

    def application_manifest_path(self, apk_name: str) -> Path:
        return (
            self.resources_dir
            / "application_code"
            / apk_name
            / "resources"
            / "AndroidManifest.xml"
        )

    def application_code_dir(self, apk_name: str) -> Path:
        return self.resources_dir / "application_code" / apk_name / "sources"

    def android_cg_path(self, v: str) -> Path:
        return self.resources_dir / "android_cg" / f"android{v}" / f"android{v}_cg.txt"

    def apk_cg_path(self, apk_name: str) -> Path:
        return self.resources_dir / "apk_cg" / apk_name / f"{apk_name}_cg.txt"

    @model_validator(mode="before")
    @classmethod
    def apply_preset_config(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        PRESET_CONFIGS = {
            "baseline": {
                "enable_extract_constraint": False,
                "enable_notes": False,
                "enable_candidate_reason": False,
                "enable_candidate_correction": False,
            },
            "full": {
                "enable_extract_constraint": True,
                "enable_notes": True,
                "enable_candidate_reason": True,
                "enable_candidate_correction": True,
            },
        }

        preset = values.get("preset")
        if preset:
            if preset not in PRESET_CONFIGS:
                available = list(PRESET_CONFIGS.keys())
                raise ValueError(
                    f"Unknown preset '{preset}'. Available presets: {available}"
                )

            preset_config = PRESET_CONFIGS[preset]

            for key, preset_value in preset_config.items():
                if values.get(key) is None:
                    values[key] = preset_value

        return values


config = Config()

set_default_params(cache_dir=config.cache_dir, separate_files=True)


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
                "httpx": {
                    "handlers": ["console", "file"],
                    "level": "INFO",
                    "propagate": False,
                },
                "httpcore": {
                    "handlers": ["console", "file"],
                    "level": "INFO",
                    "propagate": False,
                },
                "openai": {
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
    if config.result_statistic_path.exists():
        with open(config.result_statistic_path, "r") as f:
            run_statistic = RunStatistic(**json.load(f))
    else:
        run_statistic = RunStatistic(
            config=RunStatistic.RunConfig(
                preset=config.preset,
                enable_extract_constraint=config.enable_extract_constraint,
                enable_notes=config.enable_notes,
                enable_candidate_reason=config.enable_candidate_reason,
                enable_candidate_correction=config.enable_candidate_correction,
                model_info=RunStatistic.RunConfig.ModelInfo(
                    model_name=config.openai_model,
                    reasoning_effort=config.reasoning_effort,
                ),
            ),
        )
    run_statistic.set_path(config.result_statistic_path)

    return run_statistic


run_statistic: RunStatistic = init_statistic()

if __name__ == "__main__":
    print(config.model_dump_json(indent=4))
