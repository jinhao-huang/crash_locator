from pathlib import Path

class Config:
    CRASH_REPORTS_DIR: Path = Path.cwd() / "Data" / "crash_reports" / "all-0328"
    PRE_CHECK_REPORTS_DIR: Path = Path.cwd() / "Data" / "TSE25" / "pre_check"
    PRE_CHECK_REPORTS_DIR_REPORT_INFO_PATH: Path = Path("report_info.json")
    ANDROID_CG_PATH = lambda v: f"Data/AndroidCG/android{v}/android{v}_cg.txt"
    APK_CG_PATH = lambda apk_name: f"Data/ApkCG/{apk_name}/{apk_name}_cg.txt"
    ANDROID_CG_CALLED_CACHE_PATH = lambda v, hashed_signature: f"Data/CgCache/AndroidCG_called_cache/android_{v}/{hashed_signature}.json"
    ANDROID_CG_CALLER_CACHE_PATH = lambda v, hashed_signature: f"Data/CgCache/AndroidCG_caller_cache/android_{v}/{hashed_signature}.json"
    APK_CG_CALLED_CACHE_PATH = lambda apk_name, hashed_signature: f"Data/CgCache/ApkCG_called_cache/{apk_name}/{hashed_signature}.json"
    APK_CG_CALLER_CACHE_PATH = lambda apk_name, hashed_signature: f"Data/CgCache/ApkCG_caller_cache/{apk_name}/{hashed_signature}.json"
