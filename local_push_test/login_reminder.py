"""A single login check: no browser, local HTTP server or NAS connection needed."""
import argparse
import time
from pathlib import Path
from pending import PendingStore,remind_once
from desktop import WindowsDesktop

ROOT = Path(__file__).resolve().parent


def run(data_dir, *, login=False, desktop=None, delay=15):
    if login and delay:
        time.sleep(delay)
    data_dir = Path(data_dir)
    store = PendingStore(data_dir / 'pending-trial.sqlite3')
    return remind_once(store, desktop or WindowsDesktop(ROOT, data_dir),
                       reason='windows_login' if login else 'manual_test')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--login', action='store_true')
    parser.add_argument('--data-dir', type=Path, default=ROOT / '.local-test-data')
    parser.add_argument('--disable-autostart', action='store_true')
    args = parser.parse_args()
    if args.disable_autostart:
        result = WindowsDesktop(ROOT, args.data_dir).disable()
        print(result['message'])
        return
    run(args.data_dir, login=args.login)


if __name__ == '__main__':
    main()
