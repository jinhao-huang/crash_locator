from enum import Enum


class MethodType(Enum):
    JAVA = "java"
    ANDROID = "android"
    APPLICATION = "application"
    ANDROID_SUPPORT = "android_support"


def get_method_type(method_signature):
    from .parser import parse_signature

    package_name, _, _, _, _, _ = parse_signature(method_signature)
    if package_name.startswith("java"):
        return MethodType.JAVA
    elif package_name.startswith("android.support"):
        return MethodType.ANDROID_SUPPORT
    elif package_name.startswith("android") or package_name.startswith("com.android"):
        return MethodType.ANDROID
    else:
        return MethodType.APPLICATION


def method_signature_into_path(method_signature):
    from .parser import parse_signature

    package_name, class_name, _, _, _, _ = parse_signature(method_signature)
    path = (
        package_name.replace(".", "/")
        + "/"
        + class_name
        + ".java"
    )
    return path
