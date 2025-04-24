from tree_sitter import Node
from crash_locator.exceptions import MultipleChildrenFoundException


def get_parent(node: Node, parent_type: str) -> Node | None:
    """Get the parent node of the given node with the given type.

    Returns:
        The parent node if found, otherwise None.
    """
    parent = node.parent
    if parent is None or parent.type != parent_type:
        return None

    return parent


def get_child(node: Node, child_type: str) -> Node | None:
    """Get the child node of the given node with the given type.

    Returns:
        The child node if found, otherwise None.

    Raises:
        MultipleChildrenFoundException: If multiple child nodes are found.
    """
    children = node.named_children

    children_candidates = []
    for child in children:
        if child.type == child_type:
            children_candidates.append(child)

    if len(children_candidates) == 0:
        return None
    elif len(children_candidates) > 1:
        raise MultipleChildrenFoundException()
    return children_candidates[0]


def _get_type_child(
    node: Node, second_type_identifier_index: int | None = None
) -> Node | None:
    """The implementation of get_type_child.

    Args:
        node: The node to get the type child from.
        second_type_identifier_index: The index used when there are two type identifiers.
            (Reference: https://github.com/tree-sitter/tree-sitter-java/blob/master/grammar.js)

    Returns:
        The type child node if found, otherwise None.
    """
    base_types = [
        "array_type",
        "void_type",
        "integral_type",
        "floating_point_type",
        "boolean_type",
        "type_identifier",
    ]
    composite_type_to_index: dict[str, int | None] = {
        "generic_type": None,
        "scoped_type_identifier": 1,
    }

    children_candidates: list[Node] = []
    for child in node.named_children:
        if child.type in composite_type_to_index:
            base_type = _get_type_child(child, composite_type_to_index[child.type])
            if base_type is not None:
                children_candidates.append(base_type)
        elif child.type in base_types:
            children_candidates.append(child)

    candidates_count = len(children_candidates)
    if candidates_count == 0:
        return None
    elif candidates_count > 1:
        if candidates_count == 2 and all(
            child.type == "type_identifier" for child in children_candidates
        ):
            return children_candidates[second_type_identifier_index]
        raise MultipleChildrenFoundException()
    return children_candidates[0]


def get_type_child(node: Node) -> Node | None:
    """Get the type child node of the given node.

    Args:
        node: The node to get the type child from.

    Returns:
        The type child node if found, otherwise None.
    """
    return _get_type_child(node)
