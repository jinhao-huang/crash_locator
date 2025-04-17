from pathlib import Path
import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    ROOT_DIR: Path = Path.cwd()

    CRASH_REPORTS_DIR: Path = ROOT_DIR / "Data" / "crash_reports" / "all-0328"

    DEBUG: bool = os.environ.get("DEBUG", "false").lower() == "true"
    DEBUG_PRE_CHECK_REPORT_DIR: Path = Path(
        os.environ.get("DEBUG_PRE_CHECK_REPORT_DIR")
    )

    PRE_CHECK_REPORTS_DIR: Path = ROOT_DIR / "Data" / "TSE25" / "pre_check"
    PRE_CHECK_REPORT_INFO_NAME: str = "report_info.json"
    PRE_CHECK_STATISTIC_PATH: Path = PRE_CHECK_REPORTS_DIR / "statistic.json"

    APPLICATION_CODE_DIR: Path = ROOT_DIR / "Data" / "application_source_code"

    def APPLICATION_CODE_PATH(apk_name: str) -> Path:
        return Config.APPLICATION_CODE_DIR / apk_name / "sources"

    ANDROID_CG_PATH = lambda v: f"Data/AndroidCG/android{v}/android{v}_cg.txt"
    APK_CG_PATH = lambda apk_name: f"Data/ApkCG/{apk_name}/{apk_name}_cg.txt"
    ANDROID_CG_CALLED_CACHE_PATH = (
        lambda v,
        hashed_signature: f"Data/CgCache/AndroidCG_called_cache/android_{v}/{hashed_signature}.json"
    )
    ANDROID_CG_CALLER_CACHE_PATH = (
        lambda v,
        hashed_signature: f"Data/CgCache/AndroidCG_caller_cache/android_{v}/{hashed_signature}.json"
    )
    APK_CG_CALLED_CACHE_PATH = (
        lambda apk_name,
        hashed_signature: f"Data/CgCache/ApkCG_called_cache/{apk_name}/{hashed_signature}.json"
    )
    APK_CG_CALLER_CACHE_PATH = (
        lambda apk_name,
        hashed_signature: f"Data/CgCache/ApkCG_caller_cache/{apk_name}/{hashed_signature}.json"
    )
