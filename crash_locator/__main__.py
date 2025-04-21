import shutil
from crash_locator.config import Config, setup_logging
from crash_locator.utils.java_parser import get_application_code
from crash_locator.my_types import (
    ReportInfo,
    RunStatistic,
    Candidate,
    FinishedReportInfo,
    SkippedReportInfo,
    TemporarySkippedReportInfo,
)
from crash_locator.utils.llm import query_filter_candidate
from tqdm import tqdm
from tqdm.contrib.logging import logging_redirect_tqdm
import logging
import json

logger = logging.getLogger(__name__)


def llm_filter(report_info: ReportInfo) -> list[Candidate]:
    # Check all candidates before querying LLM
    for candidate in report_info.candidates:
        get_application_code(report_info.apk_name, candidate.signature)
        candidate.reasons.reason_explanation()

    # Query LLM
    return query_filter_candidate(report_info)


# Check if the buggy method is filtered
def _is_buggy_method_filtered(
    report_info: ReportInfo, remaining_candidates: list[Candidate]
) -> bool:
    for candidate in remaining_candidates:
        if candidate.signature == report_info.buggy_method:
            return False
    return True


def filter_statistic(
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


def save_statistic(statistic: RunStatistic):
    with open(Config.RESULT_STATISTIC_PATH, "w") as f:
        f.write(statistic.model_dump_json(indent=4))


if __name__ == "__main__":
    setup_logging(Config.RESULT_LOG_FILE_PATH)

    if Config.RESULT_STATISTIC_PATH.exists():
        with open(Config.RESULT_STATISTIC_PATH, "r") as f:
            statistic = RunStatistic(**json.load(f))
    else:
        statistic = RunStatistic()

    if Config.DEBUG:
        work_list = [Config.DEBUG_PRE_CHECK_REPORT_DIR]
    else:
        work_list = Config.PRE_CHECK_REPORTS_DIR.iterdir()

    with logging_redirect_tqdm():
        for pre_check_report_dir in tqdm(list(work_list), desc="Processing reports"):
            save_statistic(statistic)

            logger.info(f"Processing report {pre_check_report_dir.name}")
            logger.debug(f"Report path: {pre_check_report_dir}")

            report_name = pre_check_report_dir.name
            if report_name in statistic.finished_reports:
                logger.info(f"Report {report_name} already processed")
                continue

            report_path = pre_check_report_dir / Config.PRE_CHECK_REPORT_INFO_NAME
            with open(report_path, "r") as f:
                report_info = ReportInfo(**json.load(f))

            if len(report_info.candidates) == 1:
                statistic.finished_reports[report_name] = SkippedReportInfo()
                continue

            shutil.copytree(
                pre_check_report_dir,
                Config.RESULT_REPORT_DIR(report_name),
            )
            remaining_candidates = llm_filter(report_info)
            filter_statistic(report_info, remaining_candidates, statistic)
            statistic.finished_reports[report_name] = FinishedReportInfo(
                total_candidates_count=len(report_info.candidates),
                remaining_candidates_count=len(remaining_candidates),
                is_buggy_method_filtered=_is_buggy_method_filtered(
                    report_info, remaining_candidates
                ),
            )

    logger.info(f"Statistic: {statistic}")
