from .config_loader import config
from .logging_config import setup_logging
if __name__ == "__main__":
    logging_level = config.scrapyd().get('logging_level', 'INFO')
    setup_logging(logging_level)
    from .api import run  # Import after logging is configured
    run()
