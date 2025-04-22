import shutil
from pathlib import Path
import concurrent.futures
from crash_locator.config import (
    Config,
    setup_logging,
    set_thread_logger,
    clear_thread_logger,
    run_statistic,
)
from crash_locator.my_types import (
    ReportInfo,
    RunStatistic,
    Candidate,
    ProcessedReportInfo,
    SkippedReportInfo,
    FailedReportInfo,
)
from crash_locator.utils.llm import query_filter_candidate
from tqdm import tqdm
from tqdm.contrib.logging import logging_redirect_tqdm
import logging
import json
import traceback
from multiprocessing import Process

logger = logging.getLogger()


def _is_buggy_method_filtered(
    report_info: ReportInfo, remaining_candidates: list[Candidate]
) -> bool:
    for candidate in remaining_candidates:
        if candidate.signature == report_info.buggy_method:
            return False
    return True


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

        if report_name in statistic.finished_reports_detail:
            task_logger.info(f"Report {report_name} already processed, skip it")
            return

        report_path = pre_check_report_dir / Config.PRE_CHECK_REPORT_INFO_NAME
        if not report_path.exists():
            task_logger.error(f"Report info file {report_path} does not exist")
            return

        with open(report_path, "r") as f:
            report_info = ReportInfo(**json.load(f))

        if len(report_info.candidates) == 1:
            task_logger.info(f"Report {report_name} has only one candidate, skip it")
            statistic.add_report(report_name, SkippedReportInfo())
            return

        _copy_report(report_name, task_logger)

        retained_candidates = query_filter_candidate(report_info)

        statistic.add_report(
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
        return
    finally:
        clear_thread_logger()


def _tpe_runner():
    setup_logging(Config.RESULT_LOG_FILE_PATH)
    logger.info("Start processing reports")
    logger.info(f"Maximum worker threads: {Config.MAX_WORKERS}")

    work_list = _get_work_list()
    logger.info(f"Found {len(work_list)} reports to process")

    with logging_redirect_tqdm():
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=Config.MAX_WORKERS
        ) as executor:
            future_to_report = {
                executor.submit(
                    _process_report, report_dir, run_statistic, report_dir.name
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
                    run_statistic.add_report(
                        report_name,
                        FailedReportInfo(
                            exception_type=e.__class__.__name__,
                            error_message=str(e),
                        ),
                    )

    logger.info(f"Statistic: {run_statistic}")


def run():
    try:
        process = Process(target=_tpe_runner)
        process.start()
        process.join()
    except KeyboardInterrupt:
        process.terminate()
        process.join()
