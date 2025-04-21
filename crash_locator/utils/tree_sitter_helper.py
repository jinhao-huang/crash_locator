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
