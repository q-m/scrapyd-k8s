import logging
import sys
from .api import run
from .config import Config
from .joblogs import joblogs_init

def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(name)s [%(levelname)s]: %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )

if __name__ == "__main__":
    setup_logging()
    config = Config()
    joblogs_init(config)
    run()
