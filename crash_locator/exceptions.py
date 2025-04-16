class EmptyExceptionInfoException(Exception):
    def __init__(self, message="Exception information is empty"):
        self.message = message
        super().__init__(self.message)


class InvalidSignatureException(Exception):
    def __init__(self, message="Invalid signature"):
        self.message = message
        super().__init__(self.message)
