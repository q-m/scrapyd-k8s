import logging
import sys
from .api import run

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
    run()
