import logging
from .config import Config
from tqdm import tqdm
from tqdm.contrib.logging import logging_redirect_tqdm
import shutil

logger = logging.getLogger(__name__)

if __name__ == "__main__":
    crash_reports_dir = Config.CRASH_REPORTS_DIR
    pre_check_reports_dir = Config.PRE_CHECK_REPORTS_DIR
    work_list = crash_reports_dir.iterdir()
    
    with logging_redirect_tqdm():
        for crash_report_dir in tqdm(list(work_list)):
            report_name = crash_report_dir.name
            crash_report_path = crash_report_dir / f"{report_name}.json"
            if not crash_report_path.exists():
                logger.error(f"Crash report {report_name} not found")
                continue

            pre_check_report_path = pre_check_reports_dir / report_name
            pre_check_report_path.mkdir(parents=True, exist_ok=True)
            shutil.copy(crash_report_path, pre_check_report_path)
            
            logger.info(f"Crash report {report_name} found")
