import argparse

from .api import config, run

def argparser():
    parser = argparse.ArgumentParser(
        prog='scrapyd-k8s',
        description='Deploying and running spiders on container infrastructure, with the scrapyd protocol.'
    )
    parser.add_argument('-c', '--config', action='append', default=['scrapyd_k8s.conf'],
                        help='Load configuration file (can be multiple)')
    return parser

if __name__ == "__main__":
    parser = argparser()
    args = parser.parse_args()
    config.read(args.config)

    run()
