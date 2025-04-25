import shutil
from pathlib import Path
import asyncio
from crash_locator.config import (
    Config,
    setup_logging,
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
from tqdm import tqdm
import logging
import json
import traceback

logger = logging.getLogger(__name__)


def _is_buggy_method_filtered(
    report_info: ReportInfo, remaining_candidates: list[Candidate]
) -> bool:
    for candidate in remaining_candidates:
        if candidate.signature == report_info.buggy_method:
            return False
    return True


def _get_work_list() -> list[Path]:
    logger.info(f"Process all reports in {Config.PRE_CHECK_REPORTS_DIR}")
    work_list = []
    for report_dir in Config.PRE_CHECK_REPORTS_DIR.iterdir():
        if not report_dir.is_dir():
            continue

        report_name = report_dir.name
        report_info_path = Config.PRE_CHECK_REPORT_INFO_PATH(report_name)
        if not report_info_path.exists():
            continue

        if Config.DEBUG and report_name not in Config.DEBUG_PRE_CHECK_REPORTS:
            continue

        if report_name in run_statistic.finished_reports_detail:
            finished_report = run_statistic.finished_reports_detail[report_name]
            if (not isinstance(finished_report, FailedReportInfo)) or (
                Config.RETRY_FAILED_REPORTS is False
            ):
                continue
            else:
                run_statistic.remove_report(report_name)
                logger.info(f"Report {report_name} failed, retry it, ")

        work_list.append(report_dir)

    logger.info(f"Found {len(work_list)} reports to process")
    logger.debug(f"Pending reports: {work_list}")
    return work_list


def _copy_report(report_name: str):
    target_dir = Config.RESULT_REPORT_DIR(report_name)
    target_dir.mkdir(parents=True, exist_ok=True)

    crash_report = Config.CRASH_REPORT_PATH(report_name)
    logger.info(f"Copy `{crash_report}` of {report_name} to {target_dir}")
    shutil.copy(crash_report, target_dir)

    report_info = Config.PRE_CHECK_REPORT_INFO_PATH(report_name)
    logger.info(f"Copy `{report_info}` of {report_name} to {target_dir}")
    shutil.copy(report_info, target_dir)


class TaskAdapter(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        return f"[Task {self.extra['task_name']}] {msg}", kwargs


async def _process_report(
    pre_check_report_dir: Path,
    statistic: RunStatistic,
    task_name: str,
    semaphore: asyncio.Semaphore,
):
    from crash_locator.utils.llm import query_filter_candidate

    async with semaphore:
        report_name = pre_check_report_dir.name
        logger.info(f"Processing report {report_name}")
        logger.debug(f"Report path: {pre_check_report_dir}")

        with open(Config.PRE_CHECK_REPORT_INFO_PATH(report_name), "r") as f:
            report_info = ReportInfo(**json.load(f))

        if len(report_info.candidates) == 1:
            logger.info(f"Report {report_name} has only one candidate, skip it")
            statistic.add_report(report_name, SkippedReportInfo())
            return

        _copy_report(report_name)

        try:
            retained_candidates = await query_filter_candidate(report_info)

        except asyncio.CancelledError:
            logger.info(f"Task {task_name} cancelled")
            raise
        except Exception as e:
            logger.critical(f"Error processing report: {e}")
            logger.critical(f"{traceback.format_exc()}")
            statistic.add_report(
                task_name,
                FailedReportInfo(
                    exception_type=e.__class__.__name__,
                    error_message=str(e),
                ),
            )
        else:
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
            logger.info(f"Finished processing report {report_name}")


async def run():
    setup_logging(Config.RESULT_DIR)
    logger.info("Start processing reports")
    logger.info(f"Maximum worker threads: {Config.MAX_WORKERS}")

    work_list = _get_work_list()
    logger.info(f"Found {len(work_list)} reports to process")

    semaphore = asyncio.Semaphore(Config.MAX_WORKERS)
    tasks: list[asyncio.Task] = []
    for report_dir in work_list:
        tasks.append(
            asyncio.create_task(
                _process_report(report_dir, run_statistic, report_dir.name, semaphore),
                name=report_dir.name,
            )
        )

    try:
        for task in tqdm(
            asyncio.as_completed(tasks), total=len(tasks), desc="Processing reports"
        ):
            await task
        logger.info(f"Statistic: {run_statistic}")
    except asyncio.CancelledError:
        logger.info("Received CancelledError signal, program will exit")
        for task in tasks:
            task.cancel()
