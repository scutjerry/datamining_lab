"""Run from any working directory: python scripts/run_member_a.py collect|clean|ner|validate|all."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
sys.stdout.reconfigure(encoding='utf-8')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=['collect', 'clean', 'ner', 'validate', 'all'])
    parser.add_argument('--refresh', action='store_true', help='Re-download source pages explicitly')
    args = parser.parse_args()
    if args.stage in ('collect', 'all'):
        from member_a.collect import collect
        collect(refresh=args.refresh)
    if args.stage in ('clean', 'all'):
        from member_a.clean import clean_all
        clean_all()
    if args.stage in ('ner', 'all'):
        from member_a.entities import extract_all
        extract_all()
    if args.stage in ('validate', 'all'):
        from member_a.validate import validate_all
        validate_all()


if __name__ == '__main__':
    main()
