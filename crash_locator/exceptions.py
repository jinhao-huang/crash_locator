class PreCheckException(Exception):
    def __init__(self, message="Pre-check failed"):
        self.message = message
        super().__init__(self.message)


class EmptyExceptionInfoException(PreCheckException):
    def __init__(self, message="Exception information is empty"):
        self.message = message
        super().__init__(self.message)


class InvalidSignatureException(PreCheckException):
    def __init__(self, message="Invalid signature"):
        self.message = message
        super().__init__(self.message)


class InvalidFrameworkStackException(PreCheckException):
    def __init__(self, message="Invalid framework stack"):
        self.message = message
        super().__init__(self.message)


class NoBuggyMethodCandidatesException(PreCheckException):
    def __init__(self, message="No buggy method candidates in the report"):
        self.message = message
        super().__init__(self.message)


class CandidateCodeNotFoundException(PreCheckException):
    def __init__(self, candidate_name: str):
        self.message = f"Candidate code not found for {candidate_name}"
        super().__init__(self.message)


class NoTerminalAPIException(PreCheckException):
    def __init__(self, message="No terminal API found in the report"):
        self.message = message
        super().__init__(self.message)


class MethodCodeException(Exception):
    def __init__(self, message="Method code cannot be retrieved"):
        self.message = message
        super().__init__(self.message)


class MultipleMethodsCodeError(MethodCodeException):
    def __init__(self, message="Multiple methods found with the same name."):
        self.message = message
        super().__init__(self.message)


class NoMethodFoundCodeError(MethodCodeException):
    def __init__(self, message="No method found in the report"):
        self.message = message
        super().__init__(self.message)


class MethodFileNotFoundException(MethodCodeException):
    def __init__(self, message="Method file not found"):
        self.message = message
        super().__init__(self.message)


class UnknownException(Exception):
    def __init__(self, message="Unknown exception"):
        self.message = message
        super().__init__(self.message)


class TreeSitterException(Exception):
    def __init__(self, message="Tree Sitter exception"):
        self.message = message
        super().__init__(self.message)


class MultipleChildrenFoundException(TreeSitterException):
    def __init__(self, message="Multiple children found"):
        self.message = message
        super().__init__(self.message)


class LLMException(Exception):
    def __init__(self, message="LLM exception"):
        self.message = message
        super().__init__(self.message)


class UnExpectedResponseException(LLMException):
    def __init__(self, message="Unexpected response from LLM"):
        self.message = message
        super().__init__(self.message)


class LoggerNotFoundException(Exception):
    def __init__(self, message="Logger not found"):
        self.message = message
        super().__init__(self.message)


class TaskCancelledException(Exception):
    def __init__(self, message="Task cancelled"):
        self.message = message
        super().__init__(self.message)
