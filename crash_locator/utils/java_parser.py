from tree_sitter import Language, Parser, Node
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

JAVA_LANGUAGE = Language(tree_sitter_java.language())
parser = Parser(JAVA_LANGUAGE)


def get_application_code(
    apk_name: str,
    method_signature: MethodSignature,
) -> str:
    application_code_path = Config.APPLICATION_CODE_PATH(apk_name)
    return _get_method_code_in_file(
        application_code_path / method_signature.into_path(),
        method_signature.method_name,
        method_signature.return_type.split(".")[-1]
        if method_signature.return_type
        else None,
        [param.split(".")[-1] for param in method_signature.parameters]
        if method_signature.parameters is not None
        else None,
    )


def _get_method_code_in_file(
    file_path: Path,
    method_name: str,
    return_type: str | None = None,
    arguments: list[str] | None = None,
) -> str:
    if not file_path.exists():
        raise MethodFileNotFoundException()

    with open(file_path, "r", encoding="utf-8") as f:
        source_code = f.read()
    tree = parser.parse(bytes(source_code, "utf8"))

    if return_type is not None:
        return_type_query = f'(_) @type (#eq? @type "{return_type}") .'
    if arguments is not None:
        argument_query = " . ".join(
            [
                f"""
            (
                formal_parameter
                . (_) @para{index} (#eq? @para{index} "{argument}")
            )
            """
                for index, argument in enumerate(arguments)
            ]
        )
        argument_query = f". {argument_query} ."

    query_string = f"""
    (
        method_declaration
        {return_type_query if return_type is not None else ""}
        (identifier) @name (#eq? @name "{method_name}")
        (formal_parameters)
    ) @method"""

    query = JAVA_LANGUAGE.query(query_string)
    captures = query.captures(tree.root_node)

    method = _filter_methods_by_parameters(captures.get("method"), arguments)
    if method is None or len(method) == 0:
        raise NoMethodFoundCodeError()
    elif len(method) > 1:
        raise MultipleMethodsCodeError()
    else:
        method = method[0]

    return method.text.decode("utf8")


def _get_formal_parameters(method: Node) -> Node | None:
    for node in method.named_children:
        if node.type == "formal_parameters":
            return node
    return None


def _filter_methods_by_parameters(
    methods: list[Node] | None,
    parameters: list[str] | None,
) -> list[Node] | None:
    if methods is None:
        return None
    if parameters is None:
        return methods

    filtered_methods = []
    for method in methods:
        formal_parameters = _get_formal_parameters(method)
        if formal_parameters is None:
            raise UnknownException()

        if formal_parameters.named_child_count != len(parameters):
            continue

        matched = True
        for parameter, expected_parameter in zip(
            formal_parameters.named_children, parameters
        ):
            type_identifier = parameter.named_children[0]
            if type_identifier.text.decode("utf8") != expected_parameter:
                matched = False
                break
        if matched:
            filtered_methods.append(method)

    return filtered_methods
