class PreCheckException(Exception):
    def __init__(self, message="Pre-check failed"):
        self.message = message
        super().__init__(self.message)


class EmptyExceptionInfoException(PreCheckException):
    def __init__(self, message="Exception information is empty"):
        self.message = message
        super().__init__(self.message)


class InvalidSignatureException(Exception):
    def __init__(self, message="Invalid signature"):
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
