import argparse
import json
import sys
from .client import run

parser = argparse.ArgumentParser(description='CPU DumbBot for explicitly selected Classic no-press games')
parser.add_argument('--config', required=True, help='Private JSON configuration outside the web root')
parser.add_argument('--submit', action='store_true', help='Send orders; otherwise print a dry run')
args = parser.parse_args()
try:
    with open(args.config, encoding='utf-8') as source:
        config = json.load(source)
    result = run(config, args.submit)
except (OSError, ValueError, TypeError) as error:
    print('Bot startup failed: ' + str(error), file=sys.stderr)
    result = 1
sys.exit(result)
