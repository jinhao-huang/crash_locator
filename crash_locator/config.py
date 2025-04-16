from pathlib import Path

class Config:
    CRASH_REPORTS_DIR: Path = Path.cwd() / "Data" / "crash_reports" / "all-0328"
    PRE_CHECK_REPORTS_DIR: Path = Path.cwd() / "Data" / "TSE25" / "pre_check"
