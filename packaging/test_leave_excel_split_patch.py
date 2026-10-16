"""Run the existing installer safety checks against the split-history release."""
import unittest

import build_leave_excel_split_patch as split
import test_leave_excel_patch as existing_tests


if __name__ == '__main__':
    existing_tests.patch = split
    unittest.main(module=existing_tests)
