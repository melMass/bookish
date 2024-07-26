import logging


# Add a null handler to the carrier logging tree to silence them by default.
# (In Python 3 if a logger doesn't have a handler Python will add one when the
# logger is used.)
logger = logging.getLogger("bookish")
logger.addHandler(logging.NullHandler())
