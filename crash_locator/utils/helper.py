from crash_locator.my_types import PackageType


def get_method_type(method_signature):
    from .parser import parse_signature

    package_name, _, _, _, _, _ = parse_signature(method_signature)
    if package_name.startswith("java"):
        return PackageType.JAVA
    elif package_name.startswith("android.support"):
        return PackageType.ANDROID_SUPPORT
    elif package_name.startswith("android") or package_name.startswith("com.android"):
        return PackageType.ANDROID
    else:
        return PackageType.APPLICATION


def method_signature_into_path(method_signature):
    from .parser import parse_signature

    package_name, class_name, _, _, _, _ = parse_signature(method_signature)
    path = package_name.replace(".", "/") + "/" + class_name + ".java"
    return path
