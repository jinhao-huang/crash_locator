import shutil
from pathlib import Path
import asyncio
from crash_locator.config import (
    config,
    setup_logging,
    run_statistic,
)
from crash_locator.my_types import (
    ReasonTypeLiteral,
    ReportInfo,
    RunStatistic,
    Candidate,
    ProcessedReportInfo,
    SkippedReportInfo,
    FailedReportInfo,
)
from tqdm import tqdm
from tqdm.contrib.logging import logging_redirect_tqdm
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
    logger.info(f"Process all reports in {config.pre_check_reports_dir}")
    work_list = []
    for report_dir in config.pre_check_reports_dir.iterdir():
        if not report_dir.is_dir():
            continue

        report_name = report_dir.name
        report_info_path = config.pre_check_report_info_path(report_name)
        if not report_info_path.exists():
            continue

        if config.debug and report_name not in config.debug_pre_check_reports:
            continue

        if report_name in run_statistic.finished_reports_detail:
            finished_report = run_statistic.finished_reports_detail[report_name]
            if (not isinstance(finished_report, FailedReportInfo)) or (
                config.retry_failed_reports is False
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
    target_dir = config.result_report_dir(report_name)
    target_dir.mkdir(parents=True, exist_ok=True)

    crash_report = config.crash_report_path(report_name)
    logger.info(f"Copy `{crash_report}` of {report_name} to {target_dir}")
    shutil.copy(crash_report, target_dir)

    report_info = config.pre_check_report_info_path(report_name)
    logger.info(f"Copy `{report_info}` of {report_name} to {target_dir}")
    shutil.copy(report_info, target_dir)


class TaskAdapter(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        return f"[Task {self.extra['task_name']}] {msg}", kwargs


def _candidate_correction(
    report_info: ReportInfo, retained_candidates: list[Candidate]
) -> None:
    for candidate in report_info.candidates:
        if candidate in retained_candidates:
            continue

        keep_flag = False
        if candidate.signature.method_name in [
            "onStart",
            "onDestroy",
            "onCreate",
            "onPause",
            "onResume",
        ]:
            keep_flag = True

        if candidate.reasons.reason_type in [
            ReasonTypeLiteral.NOT_OVERRIDE_METHOD,
            ReasonTypeLiteral.KEY_VAR_3,
        ]:
            keep_flag = True

        if keep_flag:
            retained_candidates.append(candidate)


async def _process_report(
    pre_check_report_dir: Path,
    statistic: RunStatistic,
    task_name: str,
    semaphore: asyncio.Semaphore,
):
    from crash_locator.utils.llm import filter_candidate

    async with semaphore:
        report_name = pre_check_report_dir.name
        logger.info(f"Processing report {report_name}")
        logger.debug(f"Report path: {pre_check_report_dir}")

        with open(config.pre_check_report_info_path(report_name), "r") as f:
            report_info = ReportInfo(**json.load(f))

        if len(report_info.candidates) == 1:
            logger.info(f"Report {report_name} has only one candidate, skip it")
            statistic.add_report(report_name, SkippedReportInfo())
            return

        _copy_report(report_name)

        try:
            retained_candidates = await filter_candidate(report_info)

            if config.enable_candidate_correction:
                _candidate_correction(report_info, retained_candidates)

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
    setup_logging(config.result_dir)
    logger.info("Start processing reports")
    logger.info(f"Maximum worker threads: {config.max_workers}")

    work_list = _get_work_list()
    logger.info(f"Found {len(work_list)} reports to process")

    semaphore = asyncio.Semaphore(config.max_workers)
    tasks: list[asyncio.Task] = []
    for report_dir in work_list:
        tasks.append(
            asyncio.create_task(
                _process_report(report_dir, run_statistic, report_dir.name, semaphore),
                name=report_dir.name,
            )
        )

    try:
        with logging_redirect_tqdm():
            for task in tqdm(
                asyncio.as_completed(tasks),
                total=len(tasks),
                desc="Processing reports",
            ):
                await task
        logger.info("All tasks finished")
        logger.debug(f"Statistic: {run_statistic}")
    except asyncio.CancelledError:
        logger.info("Received CancelledError signal, program will exit")
        for task in tasks:
            task.cancel()
