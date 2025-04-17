from beartype.claw import beartype_this_package  # <-- boilerplate for victory
import logging
import sys

beartype_this_package()

logger = logging.getLogger()
streamHandler = logging.StreamHandler(sys.stdout)
streamHandler.setFormatter(
    logging.Formatter("(%(asctime)s)[%(levelname)s] %(message)s")
)
logger.addHandler(streamHandler)
logger.setLevel(logging.ERROR)
