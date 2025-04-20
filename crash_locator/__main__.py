from crash_locator.config import Config, setup_logging
from crash_locator.utils.java_parser import get_application_code
from crash_locator.my_types import (
    ReportInfo,
    RunStatistic,
    Candidate,
    ReportRunInfo,
    ReportStatus,
)
from crash_locator.exceptions import MethodCodeException
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


def filter_statistic(
    report_info: ReportInfo,
    remaining_candidates: list[Candidate],
    statistic: RunStatistic,
):
    statistic.processed_reports += 1
    filtered_methods_nums = len(report_info.candidates) - len(remaining_candidates)
    statistic.filtered_method_count += filtered_methods_nums
    for candidate in remaining_candidates:
        if candidate.signature == report_info.buggy_method:
            return

    statistic.filtered_buggy_method_count += 1


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
            if not report_path.exists():
                logger.error(f"Crash report {report_name} not found")
                statistic.invalid_reports += 1
                continue
            else:
                with open(report_path, "r") as f:
                    report_info = ReportInfo(**json.load(f))

            invalid_report_flag = False
            for candidate in report_info.candidates:
                candidate_signature = candidate.signature
                logger.info(f"Processing candidate {candidate_signature}")
                try:
                    if len(report_info.candidates) == 1:
                        statistic.finished_reports[report_name] = ReportRunInfo(
                            status=ReportStatus.SKIPPED
                        )
                        continue
                    remaining_candidates = llm_filter(report_info)
                    filter_statistic(report_info, remaining_candidates, statistic)
                    statistic.finished_reports[report_name] = ReportRunInfo(
                        status=ReportStatus.FINISHED
                    )
                except MethodCodeException as e:
                    logger.error(
                        f"Candidate `{candidate_signature}` processing failed: {e}"
                    )
                    statistic.invalid_methods += 1
                    invalid_report_flag = True
                    if "$" in candidate_signature:
                        statistic.dollar_sign_invalid_methods += 1
                    continue

                statistic.valid_methods += 1

            if invalid_report_flag:
                statistic.invalid_reports += 1
                logger.error(
                    f"Invalid report {report_name}\nfile: {pre_check_report_dir}\napplication code dir: {Config.APPLICATION_CODE_PATH(report_info.apk_name)}"
                )
            else:
                statistic.valid_reports += 1
                statistic.valid_reports_methods += len(report_info.candidates)

    logger.info(f"Statistic: {statistic}")
