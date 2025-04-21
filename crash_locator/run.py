import shutil
from pathlib import Path
import concurrent.futures
from crash_locator.config import (
    Config,
    setup_logging,
    set_thread_logger,
    clear_thread_logger,
)
from crash_locator.my_types import (
    ReportInfo,
    RunStatistic,
    Candidate,
    ProcessedReportInfo,
    SkippedReportInfo,
    FailedReportInfo,
    FinishedReport,
)
from crash_locator.utils.llm import query_filter_candidate
from tqdm import tqdm
from tqdm.contrib.logging import logging_redirect_tqdm
import logging
import json
import threading
import traceback

logger = logging.getLogger(__name__)
statistic_lock = threading.Lock()


def _is_buggy_method_filtered(
    report_info: ReportInfo, remaining_candidates: list[Candidate]
) -> bool:
    for candidate in remaining_candidates:
        if candidate.signature == report_info.buggy_method:
            return False
    return True


def _save_statistic(statistic: RunStatistic):
    with open(Config.RESULT_STATISTIC_PATH, "w") as f:
        f.write(statistic.model_dump_json(indent=4))


def _add_statistic(
    statistic: RunStatistic,
    report_name: str,
    finished_report_info: FinishedReport,
):
    with statistic_lock:
        if isinstance(finished_report_info, ProcessedReportInfo):
            statistic.processed_reports += 1
            statistic.processed_candidates += (
                finished_report_info.total_candidates_count
            )
            statistic.filtered_candidates += (
                finished_report_info.filtered_candidates_count
            )
            statistic.retained_candidates += (
                finished_report_info.retained_candidates_count
            )
            if finished_report_info.is_buggy_method_filtered:
                statistic.filtered_buggy_method += 1
            statistic.finished_reports_detail[report_name] = finished_report_info
        elif isinstance(finished_report_info, SkippedReportInfo):
            statistic.skipped_reports += 1
        elif isinstance(finished_report_info, FailedReportInfo):
            statistic.failed_reports += 1
            statistic.finished_reports_detail[report_name] = finished_report_info

        _save_statistic(statistic)


def _get_statistic() -> RunStatistic:
    if Config.RESULT_STATISTIC_PATH.exists():
        logger.info(f"Load statistic from {Config.RESULT_STATISTIC_PATH}")
        with open(Config.RESULT_STATISTIC_PATH, "r") as f:
            statistic = RunStatistic(**json.load(f))
    else:
        logger.info("No statistic file found, create a new one")
        statistic = RunStatistic()
    return statistic


def _get_work_list() -> list[Path]:
    if Config.DEBUG:
        logger.info(f"Use debug mode, only process {Config.DEBUG_PRE_CHECK_REPORT_DIR}")
        return [Config.DEBUG_PRE_CHECK_REPORT_DIR]
    else:
        logger.info(f"Process all reports in {Config.PRE_CHECK_REPORTS_DIR}")
        return list(Config.PRE_CHECK_REPORTS_DIR.iterdir())


def _copy_report(report_name: str, task_logger: logging.LoggerAdapter):
    original_dir = Config.PRE_CHECK_REPORTS_DIR / report_name
    target_dir = Config.RESULT_DIR / report_name

    target_dir.mkdir(parents=True, exist_ok=True)

    original_report = original_dir / f"{report_name}.json"
    target_report = target_dir / f"{report_name}.json"
    if not target_report.exists():
        task_logger.info(f"Copy `{original_report}` of {report_name} to {target_dir}")
        shutil.copy(original_report, target_report)

    original_report_info = original_dir / Config.PRE_CHECK_REPORT_INFO_NAME
    target_report_info = target_dir / Config.PRE_CHECK_REPORT_INFO_NAME
    if not target_report_info.exists():
        task_logger.info(
            f"Copy `{original_report_info}` of {report_name} to {target_dir}"
        )
        shutil.copy(original_report_info, target_report_info)


class TaskAdapter(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        return f"[Task {self.extra['task_name']}] {msg}", kwargs


def _process_report(
    pre_check_report_dir: Path, statistic: RunStatistic, task_name: str
):
    task_logger = TaskAdapter(logger, {"task_name": task_name})
    set_thread_logger(task_logger)

    try:
        report_name = pre_check_report_dir.name
        task_logger.info(f"Processing report {report_name}")
        task_logger.debug(f"Report path: {pre_check_report_dir}")

        with statistic_lock:
            if report_name in statistic.finished_reports_detail:
                task_logger.info(f"Report {report_name} already processed, skip it")
                return report_name

        report_path = pre_check_report_dir / Config.PRE_CHECK_REPORT_INFO_NAME
        if not report_path.exists():
            task_logger.error(f"Report info file {report_path} does not exist")
            return None

        with open(report_path, "r") as f:
            report_info = ReportInfo(**json.load(f))

        if len(report_info.candidates) == 1:
            task_logger.info(f"Report {report_name} has only one candidate, skip it")
            _add_statistic(statistic, report_name, SkippedReportInfo())
            return report_name

        _copy_report(report_name, task_logger)

        retained_candidates = query_filter_candidate(report_info)

        _add_statistic(
            statistic,
            report_name,
            ProcessedReportInfo(
                total_candidates_count=len(report_info.candidates),
                retained_candidates_count=len(retained_candidates),
                is_buggy_method_filtered=_is_buggy_method_filtered(
                    report_info, retained_candidates
                ),
            ),
        )
        task_logger.info(f"Finished processing report {report_name}")
        return report_name
    finally:
        clear_thread_logger()


def run():
    setup_logging(Config.RESULT_LOG_FILE_PATH)
    logger.info("Start processing reports")
    logger.info(f"Maximum worker threads: {Config.MAX_WORKERS}")

    statistic = _get_statistic()
    work_list = _get_work_list()
    logger.info(f"Found {len(work_list)} reports to process")

    with logging_redirect_tqdm():
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=Config.MAX_WORKERS
        ) as executor:
            future_to_report = {
                executor.submit(
                    _process_report, report_dir, statistic, report_dir.name
                ): report_dir.name
                for report_dir in work_list
            }

            for future in tqdm(
                concurrent.futures.as_completed(future_to_report),
                total=len(future_to_report),
                desc="Processing reports",
            ):
                report_name = future_to_report[future]
                try:
                    future.result()
                except Exception as e:
                    logger.critical(f"Error processing report: {e}")
                    logger.critical(f"{traceback.format_exc()}")
                    _add_statistic(
                        statistic,
                        report_name,
                        FailedReportInfo(
                            exception_type=e.__class__.__name__,
                            error_message=str(e),
                        ),
                    )

    logger.info(f"Statistic: {statistic}")
