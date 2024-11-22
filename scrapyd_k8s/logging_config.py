import logging
import sys

def setup_logging(log_level):
    if not log_level:
        log_level = 'INFO'  # Default to INFO if logging_level is None

    level_name = str(log_level).upper()
    numeric_level = logging.getLevelName(level_name)
    if not isinstance(numeric_level, int):
        raise ValueError(
            f"Invalid logging level '{log_level}'."
        )
    logging.basicConfig(
        level=numeric_level,
        format='%(asctime)s %(name)s [%(levelname)s]: %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)]
    )