"""Compatibility entry point for the current purchase-only browser journey."""
from pathlib import Path
import runpy

if __name__=='__main__':
    runpy.run_path(str(Path(__file__).with_name('check_purchase_features.py')),run_name='__main__')
