import logging
from .config import Config
from tqdm import tqdm
from tqdm.contrib.logging import logging_redirect_tqdm

logger = logging.getLogger(__name__)

if __name__ == "__main__":
    crash_reports_path = Config.CRASH_REPORT_PATH
    pre_check_path = Config.PRE_CHECK_PATH
    work_list = crash_reports_path.iterdir()
    
    with logging_redirect_tqdm():
        for crash_report_dir in tqdm(list(work_list)):
            report_name = crash_report_dir.name
            crash_report_path = crash_report_dir / f"{report_name}.json"
            if not crash_report_path.exists():
                logger.error(f"Crash report {report_name} not found")
                continue
            
            logger.info(f"Crash report {report_name} found")
