from crash_locator.config import Config
from crash_locator.utils.java_parser import get_application_code
from crash_locator.my_types import ReportInfo, RunStatistic
from crash_locator.exceptions import MethodCodeException
from tqdm import tqdm
from tqdm.contrib.logging import logging_redirect_tqdm
import logging
import json

logger = logging.getLogger(__name__)

if __name__ == "__main__":
    statistic = RunStatistic()
    if Config.DEBUG:
        work_list = [Config.DEBUG_PRE_CHECK_REPORT_DIR]
    else:
        work_list = Config.PRE_CHECK_REPORTS_DIR.iterdir()

    with logging_redirect_tqdm():
        for pre_check_report_dir in tqdm(list(work_list), desc="Processing reports"):
            logger.info(f"Processing report {pre_check_report_dir.name}")
            logger.debug(f"Report path: {pre_check_report_dir}")
            report_name = pre_check_report_dir.name
            report_path = pre_check_report_dir / Config.PRE_CHECK_REPORT_INFO_NAME
            if not report_path.exists():
                logger.error(f"Crash report {report_name} not found")
                statistic.invalid_reports += 1
                continue

            with open(report_path, "r") as f:
                report_info = ReportInfo(**json.load(f))

            invalid_report_flag = False
            for candidate in report_info.candidates:
                candidate_signature = candidate.signature
                logger.info(f"Processing candidate {candidate_signature}")
                try:
                    application_code = get_application_code(
                        report_info.apk_name, candidate_signature
                    )
                    reason = candidate.reasons.reason_explanation()
                except MethodCodeException as e:
                    logger.error(
                        f"Error processing candidate `{candidate_signature}`: {e}"
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

    print(statistic)
