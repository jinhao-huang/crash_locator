from tree_sitter import Language, Parser, Node
from typing import Callable
import tree_sitter_java
from pathlib import Path
from crash_locator.config import Config
from crash_locator.my_types import MethodSignature
from crash_locator.exceptions import (
    MultipleMethodsCodeError,
    NoMethodFoundCodeError,
    MethodFileNotFoundException,
    UnknownException,
)
from crash_locator.utils.tree_sitter_helper import get_parent, get_child

JAVA_LANGUAGE = Language(tree_sitter_java.language())
parser = Parser(JAVA_LANGUAGE)


def get_application_code(
    apk_name: str,
    method_signature: MethodSignature,
) -> str:
    """Get the application code for a given method signature.

    Raises:
        NoMethodFoundCodeError: No method found in the file.
        MultipleMethodsCodeError: Multiple methods found in the file.
    """
    application_code_path = Config.APPLICATION_CODE_PATH(apk_name)
    return _get_method_code_in_file(
        application_code_path / method_signature.into_path(), method_signature
    )


def _get_method_code_in_file(
    file_path: Path,
    method_signature: MethodSignature,
) -> str:
    method_name = method_signature.method_name
    return_type = (
        method_signature.return_type.split(".")[-1]
        if method_signature.return_type
        else None
    )

    if not file_path.exists():
        raise MethodFileNotFoundException()

    with open(file_path, "r", encoding="utf-8") as f:
        source_code = f.read()
    tree = parser.parse(bytes(source_code, "utf8"))

    if return_type is not None:
        return_type_query = f'(_) @type (#eq? @type "{return_type}") .'

    query_string = f"""
    (
        method_declaration
        {return_type_query if return_type is not None else ""}
        (identifier) @name (#eq? @name "{method_name}")
        (formal_parameters)
    ) @method"""

    query = JAVA_LANGUAGE.query(query_string)
    captures = query.captures(tree.root_node)

    method = _filter_methods(
        captures.get("method"),
        method_signature,
        [_methods_parameters_filter, _anonymous_class_filter],
    )
    if method is None or len(method) == 0:
        raise NoMethodFoundCodeError()
    elif len(method) > 1:
        raise MultipleMethodsCodeError()
    else:
        method = method[0]

    return method.text.decode("utf8")


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


def _methods_parameters_filter(
    methods: list[Node],
    method_signature: MethodSignature,
) -> list[Node]:
    parameters = (
        [param.split(".")[-1].split("$")[-1] for param in method_signature.parameters]
        if method_signature.parameters is not None
        else None
    )

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
            # The type of type_identifier is not unique(e.g. "type_identifier", "integer_type")
            # Use -2 index to find the type identifier
            # Use 0 index is bad due to possible existence of "modifiers"
            type_identifier = parameter.named_children[-2]
            if type_identifier.type == "generic_type":
                type_identifier = type_identifier.named_children[0]
            if type_identifier.text.decode("utf8") != expected_parameter:
                matched = False
                break
        if matched:
            filtered_methods.append(method)

    return filtered_methods


def _anonymous_class_filter(
    methods: list[Node], method_signature: MethodSignature
) -> list[Node]:
    inner_class = method_signature.inner_class
    if inner_class is None:
        return methods
    if not inner_class.split("$")[-1].isdigit():
        return methods

    retained_methods = []
    for method in methods:
        class_body = get_parent(method, "class_body")
        if class_body is None:
            continue
        line_comment = get_child(class_body, "line_comment")
        if (
            line_comment is not None
            and method_signature.full_class_name() in line_comment.text.decode("utf8")
        ):
            retained_methods.append(method)

    return retained_methods
