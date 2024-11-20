import logging
import sys

VALID_LOG_LEVELS = {
    'CRITICAL': logging.CRITICAL,
    'ERROR': logging.ERROR,
    'WARNING': logging.WARNING,
    'INFO': logging.INFO,
    'DEBUG': logging.DEBUG,
    'NOTSET': logging.NOTSET,
}

def setup_logging(logging_level):
    if not logging_level:
        logging_level = 'INFO'  # Default to INFO if logging_level is None

    level_name = str(logging_level).upper()

    if level_name not in VALID_LOG_LEVELS:
        valid_levels_str = ', '.join(VALID_LOG_LEVELS.keys())
        raise ValueError(
            f"Invalid logging level '{logging_level}'. Valid levels are: {valid_levels_str}"
        )

    logging.basicConfig(
        level=VALID_LOG_LEVELS[level_name],
        format='%(asctime)s %(name)s [%(levelname)s]: %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)]
    )
