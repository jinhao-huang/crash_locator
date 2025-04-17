from crash_locator.config import Config
from crash_locator.utils.java_parser import get_application_code
from crash_locator.my_types import MethodSignature, ReportInfo, RunStatistic
from crash_locator.exceptions import (
    MethodCodeException,
    InvalidSignatureException,
)
from tqdm import tqdm
from tqdm.contrib.logging import logging_redirect_tqdm
import logging
import json

logger = logging.getLogger(__name__)

if __name__ == "__main__":
    statistic = RunStatistic()
    work_list = Config.PRE_CHECK_REPORTS_DIR.iterdir()

    with logging_redirect_tqdm():
        for pre_check_report_dir in tqdm(list(work_list), desc="Processing reports"):
            logger.info(
                f"Processing report {pre_check_report_dir.name}, file: {pre_check_report_dir}"
            )
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
                logger.info(f"Processing candidate {candidate['Candidate Signature']}")
                try:
                    method_signature = MethodSignature(candidate["Candidate Signature"])
                    application_code = get_application_code(
                        report_info.apk_name, method_signature
                    )
                except (MethodCodeException, InvalidSignatureException) as e:
                    logger.error(
                        f"Error processing candidate {candidate['Candidate Signature']}: {e}"
                    )
                    statistic.invalid_methods += 1
                    invalid_report_flag = True
                    continue

                statistic.valid_methods += 1

            if invalid_report_flag:
                statistic.invalid_reports += 1
                logger.error(
                    f"Invalid report {report_name}\nfile: {pre_check_report_dir}\napplication code dir: {Config.APPLICATION_CODE_PATH(report_info.apk_name)}"
                )
            else:
                statistic.valid_reports += 1

    print(statistic)
