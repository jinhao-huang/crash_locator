from tree_sitter import Language, Parser, Node
from typing import Callable
import tree_sitter_java
from pathlib import Path
from crash_locator.config import config
from crash_locator.my_types import (
    MethodSignature,
    PackageType,
    Candidate,
    ClassSignature,
)
from crash_locator.exceptions import (
    MultipleMethodsCodeError,
    NoMethodFoundCodeError,
    UnknownException,
    ClassNotFoundException,
    MultipleClassesFoundCodeError,
    CodeFileNotFoundException,
    FieldNotFoundException,
)
from crash_locator.utils.tree_sitter_helper import (
    get_parent,
    get_child,
    get_type_child,
    find_ancestor_by_type,
    get_children_by_type,
)
import logging

JAVA_LANGUAGE = Language(tree_sitter_java.language())
parser = Parser(JAVA_LANGUAGE)

logger = logging.getLogger(__name__)


def get_candidate_code(
    apk_name: str,
    candidate: Candidate,
) -> str:
    """Get the application code for a given method signature.
    Recursively search the method by the extend hierarchy.

    Raises:
        ValueError: The code is not in the application code directory.
        NoMethodFoundCodeError: No method found in the file.
        MultipleMethodsCodeError: Multiple methods found in the file.
        MethodFileNotFoundException: The file does not exist.
    """
    if len(candidate.extend_hierarchy) == 0:
        extend_hierarchy = [
            ClassSignature(
                package_name=candidate.signature.package_name,
                class_name=candidate.signature.class_name,
                inner_class=candidate.signature.inner_class,
            )
        ]
    else:
        extend_hierarchy = candidate.extend_hierarchy

    for class_signature in extend_hierarchy:
        method_signature = MethodSignature(
            package_name=class_signature.package_name,
            class_name=class_signature.class_name,
            inner_class=class_signature.inner_class,
            method_name=candidate.signature.method_name,
            parameters=candidate.signature.parameters,
            return_type=candidate.signature.return_type,
        )
        if PackageType.get_package_type(method_signature) != PackageType.APPLICATION:
            raise ValueError("The code is not in the application code directory.")
        try:
            return _get_method_code_in_file(
                config.application_code_dir(apk_name) / method_signature.into_path(),
                method_signature,
            )
        except NoMethodFoundCodeError:
            continue

    raise NoMethodFoundCodeError()


def get_application_code(
    apk_name: str,
    method_signature: MethodSignature,
) -> str:
    """Get the application code for a given method signature."""
    return _get_method_code_in_file(
        config.application_code_dir(apk_name) / method_signature.into_path(),
        method_signature,
    )


def get_framework_code(
    method_signature: MethodSignature,
    android_version: str,
) -> str:
    """Get the framework code for a given method signature and android version.

    Raises:
        NoMethodFoundCodeError: No method found in the file.
        MultipleMethodsCodeError: Multiple methods found in the file.
        MethodFileNotFoundException: The file does not exist.
    """
    if method_signature.package_name.startswith("android.support"):
        return _get_method_code_in_file(
            config.android_support_code_dir() / method_signature.into_path(),
            method_signature,
        )
    else:
        if (
            method_signature.package_name == "android.location"
            and method_signature.class_name == "ILocationManager"
            and method_signature.parameters[3] == "android.location.ILocationListener"
        ):
            method_signature = MethodSignature(
                package_name=method_signature.package_name,
                class_name="LocationManager",
                inner_class=None,
                method_name=method_signature.method_name,
                return_type=method_signature.return_type,
                parameters=method_signature.parameters,
            )
            method_signature.parameters[3] = "android.location.LocationListener"
        for android_code_dir in config.android_code_dir(android_version):
            code_path = android_code_dir / method_signature.into_path()
            if code_path.exists():
                return _get_method_code_in_file(code_path, method_signature)

        raise CodeFileNotFoundException()


def list_application_methods(
    apk_name: str,
    class_signature: ClassSignature,
) -> list[str]:
    """List all methods in a given class."""
    code_path = config.application_code_dir(apk_name) / class_signature.into_path()
    if not code_path.exists():
        raise CodeFileNotFoundException()
    with open(code_path, "r", encoding="utf-8") as f:
        code_bytes = f.read().encode("utf-8")
    tree = parser.parse(code_bytes)

    query_string = f"""
    (
        class_declaration
        (identifier) @name (#eq? @name "{class_signature.class_name}")
    ) @class"""

    query = JAVA_LANGUAGE.query(query_string)
    captures = query.captures(tree.root_node)
    class_node = captures.get("class")
    if class_node is None:
        raise ClassNotFoundException()
    elif len(class_node) > 1:
        raise MultipleClassesFoundCodeError()

    class_node = class_node[0]
    class_body = get_child(class_node, "class_body")
    if class_body is None:
        raise ClassNotFoundException()
    method_nodes = get_children_by_type(class_body, "method_declaration")
    method_strings = [
        _method_node_to_signature_string(method_node, code_bytes)
        for method_node in method_nodes
    ]
    return method_strings


def list_application_fields(
    class_signature: ClassSignature,
    apk_name: str,
) -> list[str]:
    """List all fields in a given class."""
    code_path = config.application_code_dir(apk_name) / class_signature.into_path()
    if not code_path.exists():
        raise CodeFileNotFoundException()
    with open(code_path, "r", encoding="utf-8") as f:
        code_bytes = f.read().encode("utf-8")
    tree = parser.parse(code_bytes)

    field_nodes = _get_all_fields_in_class(tree.root_node, class_signature.class_name)
    field_strings = [
        _field_node_to_signature_string(field_node, code_bytes)
        for field_node in field_nodes
    ]
    return field_strings


def get_application_field(
    apk_name: str,
    class_signature: ClassSignature,
    field_name: str,
) -> str:
    """Get the application code for a given field name."""
    code_path = config.application_code_dir(apk_name) / class_signature.into_path()
    if not code_path.exists():
        raise CodeFileNotFoundException()
    with open(code_path, "r", encoding="utf-8") as f:
        code_bytes = f.read().encode("utf-8")
    tree = parser.parse(code_bytes)
    field_nodes = _get_all_fields_in_class(tree.root_node, class_signature.class_name)
    for field_node in field_nodes:
        variable_declarator = get_child(field_node, "variable_declarator")
        if variable_declarator is None:
            raise UnknownException("variable_declarator not found")
        identifier = get_child(variable_declarator, "identifier")
        if identifier is None:
            raise UnknownException("identifier not found")
        if identifier.text.decode("utf8") == field_name:
            return _field_node_to_signature_string(field_node, code_bytes)
    raise FieldNotFoundException()


def get_application_manifest(
    apk_name: str,
) -> str:
    """Get the application manifest for a given apk name."""
    manifest_path = config.application_manifest_path(apk_name)
    if not manifest_path.exists():
        raise CodeFileNotFoundException()
    with open(manifest_path, "r", encoding="utf-8") as f:
        return f.read()


def _field_node_to_signature_string(field_node: Node, code_bytes: bytes) -> str:
    start_byte_index = field_node.start_byte
    end_byte_index = field_node.end_byte
    field_code = code_bytes[start_byte_index:end_byte_index]
    return field_code.decode("utf-8")


def _get_all_fields_in_class(
    root_node: Node,
    class_name: str,
) -> list[Node]:
    query_string = f"""
    (
        class_declaration
        (identifier) @name (#eq? @name "{class_name}")
    ) @class"""

    query = JAVA_LANGUAGE.query(query_string)
    captures = query.captures(root_node)
    class_node = captures.get("class")
    if class_node is None:
        raise ClassNotFoundException()
    elif len(class_node) > 1:
        raise MultipleClassesFoundCodeError()

    class_node = class_node[0]
    class_body = get_child(class_node, "class_body")
    if class_body is None:
        raise UnknownException()
    return get_children_by_type(class_body, "field_declaration")


def _method_node_to_signature_string(method_node: Node, code_bytes: bytes) -> str:
    start_byte_index = method_node.start_byte

    last_node = None
    for child in method_node.children:
        if child.type == "block":
            break
        last_node = child

    if last_node is None:
        raise UnknownException()

    end_byte_index = last_node.end_byte
    method_code = code_bytes[start_byte_index:end_byte_index]
    return method_code.decode("utf-8")


def _get_method_code_in_file(
    file_path: Path,
    method_signature: MethodSignature,
) -> str:
    logger.debug(f"Getting method code in file: {file_path}")
    # TODO: handle <init> method
    method_name = method_signature.method_name

    if not file_path.exists():
        raise CodeFileNotFoundException()

    with open(file_path, "r", encoding="utf-8") as f:
        code_lines = f.readlines()
    tree = parser.parse(bytes("".join(code_lines), "utf8"))

    query_string = f"""
    (
        method_declaration
        (identifier) @name (#eq? @name "{method_name}")
        (formal_parameters)
    ) @method"""

    query = JAVA_LANGUAGE.query(query_string)
    captures = query.captures(tree.root_node)

    method = _filter_methods(
        captures.get("method"),
        method_signature,
        [
            _method_return_type_filter,
            _methods_parameters_filter,
            _anonymous_class_filter,
            _class_name_filter,
        ],
    )
    if method is None or len(method) == 0:
        raise NoMethodFoundCodeError()
    elif len(method) > 1:
        raise MultipleMethodsCodeError()
    else:
        method = method[0]

    method_code = code_lines[method.start_point.row : method.end_point.row + 1]
    return "".join(method_code)


def _filter_methods(
    methods: list[Node] | None,
    method_signature: MethodSignature,
    filter_functions: list[Callable[[list[Node], MethodSignature], list[Node]]],
) -> list[Node]:
    if methods is None:
        return []

    for filter_function in filter_functions:
        methods = filter_function(methods, method_signature)
        if len(methods) == 0:
            return []
    return methods


def _type_strip(type_str: list[str] | str | None) -> list[str] | str | None:
    match type_str:
        case list():
            return [_type_strip(t) for t in type_str]
        case str():
            return type_str.split(".")[-1].split("$")[-1]
        case None:
            return None
        case _:
            raise UnknownException()


def _method_return_type_filter(
    methods: list[Node],
    method_signature: MethodSignature,
) -> list[Node]:
    return_type = _type_strip(method_signature.return_type)
    if return_type is None:
        return methods

    retained_methods = []
    for method in methods:
        return_type_node = get_type_child(method)
        if return_type_node is None:
            raise UnknownException()

        if return_type_node.text.decode("utf8") != return_type:
            continue

        retained_methods.append(method)

    return retained_methods


def _methods_parameters_filter(
    methods: list[Node],
    method_signature: MethodSignature,
) -> list[Node]:
    parameters = _type_strip(method_signature.parameters)

    if parameters is None:
        return methods

    filtered_methods = []
    for method in methods:
        formal_parameters = get_child(method, "formal_parameters")
        if formal_parameters is None:
            raise UnknownException()

        if formal_parameters.named_child_count != len(parameters):
            continue

        matched = True
        for parameter, expected_parameter in zip(
            formal_parameters.named_children, parameters
        ):
            type_identifier = get_type_child(parameter)
            if type_identifier is None:
                raise UnknownException()

            if type_identifier.text.decode("utf8") != expected_parameter:
                matched = False
                break
        if matched:
            filtered_methods.append(method)

    return filtered_methods


def _is_anonymous_class(method_signature: MethodSignature) -> bool:
    return method_signature.class_list()[-1].isdigit()


def _check_anonymous_class(
    class_body_node: Node, method_signature: MethodSignature
) -> bool:
    line_comment = get_child(class_body_node, "line_comment")
    if line_comment is None:
        return False
    text = line_comment.text.decode("utf8")
    full_class_text = f"// from class: {method_signature.full_class_name()}"
    return text == full_class_text


def _anonymous_class_filter(
    methods: list[Node], method_signature: MethodSignature
) -> list[Node]:
    inner_class = method_signature.inner_class
    if inner_class is None:
        return methods
    if not _is_anonymous_class(method_signature):
        return methods

    retained_methods = []
    for method in methods:
        class_body = get_parent(method, "class_body")
        if class_body is None:
            continue
        if _check_anonymous_class(class_body, method_signature):
            retained_methods.append(method)

    return retained_methods


def _class_name_filter(
    methods: list[Node],
    method_signature: MethodSignature,
) -> list[Node]:
    class_list = method_signature.class_list()

    for class_name in reversed(class_list):
        if _is_anonymous_class(method_signature):
            class_list.pop()
        else:
            break

    retained_methods = []
    for method in methods:
        cursor_node = method
        for cursor_class in reversed(class_list):
            cursor_node = find_ancestor_by_type(cursor_node, "class_declaration")
            if cursor_node is None:
                break
            identifier = get_child(cursor_node, "identifier")
            if identifier is None:
                break
            if identifier.text.decode("utf8") != cursor_class:
                break
        else:
            retained_methods.append(method)

    return retained_methods
