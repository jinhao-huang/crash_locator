import shutil
from pathlib import Path
from crash_locator.config import Config, setup_logging
from crash_locator.my_types import (
    ReportInfo,
    RunStatistic,
    Candidate,
    FinishedReportInfo,
    SkippedReportInfo,
)
from crash_locator.utils.llm import query_filter_candidate
from tqdm import tqdm
from tqdm.contrib.logging import logging_redirect_tqdm
import logging
import json

logger = logging.getLogger(__name__)


def _is_buggy_method_filtered(
    report_info: ReportInfo, remaining_candidates: list[Candidate]
) -> bool:
    for candidate in remaining_candidates:
        if candidate.signature == report_info.buggy_method:
            return False
    return True


def _statistic(
    report_info: ReportInfo,
    remaining_candidates: list[Candidate],
    statistic: RunStatistic,
):
    statistic.processed_reports += 1
    statistic.processed_candidates += len(report_info.candidates)
    statistic.filtered_candidates += len(report_info.candidates) - len(
        remaining_candidates
    )
    statistic.retained_candidates += len(remaining_candidates)
    if _is_buggy_method_filtered(report_info, remaining_candidates):
        statistic.filtered_buggy_method += 1

    statistic.finished_reports[report_info.apk_name] = FinishedReportInfo(
        total_candidates_count=len(report_info.candidates),
        remaining_candidates_count=len(remaining_candidates),
        is_buggy_method_filtered=_is_buggy_method_filtered(
            report_info, remaining_candidates
        ),
    )


def _save_statistic(statistic: RunStatistic):
    with open(Config.RESULT_STATISTIC_PATH, "w") as f:
        f.write(statistic.model_dump_json(indent=4))


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


def _copy_report(report_name: str):
    original_dir = Config.PRE_CHECK_REPORTS_DIR / report_name
    target_dir = Config.RESULT_DIR / report_name

    target_dir.mkdir(parents=True, exist_ok=True)

    if not (target_dir / f"{report_name}.json").exists():
        logger.info(f"Copy `{report_name}.json` of {report_name} to {target_dir}")
        shutil.copy(
            original_dir / f"{report_name}.json",
            target_dir / f"{report_name}.json",
        )
    if not (target_dir / Config.PRE_CHECK_REPORT_INFO_NAME).exists():
        logger.info(
            f"Copy `{Config.PRE_CHECK_REPORT_INFO_NAME}` of {report_name} to {target_dir}"
        )
        shutil.copy(
            original_dir / Config.PRE_CHECK_REPORT_INFO_NAME,
            target_dir / Config.PRE_CHECK_REPORT_INFO_NAME,
        )


def run():
    setup_logging(Config.RESULT_LOG_FILE_PATH)
    logger.info("Start processing reports")

    statistic = _get_statistic()
    work_list = _get_work_list()

    with logging_redirect_tqdm():
        for pre_check_report_dir in tqdm(list(work_list), desc="Processing reports"):
            _save_statistic(statistic)

            logger.info(f"Processing report {pre_check_report_dir.name}")
            logger.debug(f"Report path: {pre_check_report_dir}")

            report_name = pre_check_report_dir.name
            if report_name in statistic.finished_reports:
                logger.info(f"Report {report_name} already processed, skip it")
                continue

            report_path = pre_check_report_dir / Config.PRE_CHECK_REPORT_INFO_NAME
            with open(report_path, "r") as f:
                report_info = ReportInfo(**json.load(f))

            if len(report_info.candidates) == 1:
                logger.info(f"Report {report_name} has only one candidate, skip it")
                statistic.finished_reports[report_name] = SkippedReportInfo()
                continue

            _copy_report(report_name)

            remaining_candidates = query_filter_candidate(report_info)
            _statistic(report_info, remaining_candidates, statistic)

    logger.info(f"Statistic: {statistic}")
