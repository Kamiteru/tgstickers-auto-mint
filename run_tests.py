#!/usr/bin/env python3
"""
Test Runner - wrapper to run all tests from project root
"""

import subprocess
import sys
import os


def main():
    """Run the complete test suite"""
    tests_dir = os.path.join(os.path.dirname(__file__), 'tests')
    test_runner = os.path.join(tests_dir, 'run_all_tests.py')
    
    print("🧪 TG Stickers Auto-Mint Test Suite")
    print("=" * 60)
    
    try:
        # Run the test suite
        result = subprocess.run([sys.executable, test_runner], cwd=os.path.dirname(__file__))
        sys.exit(result.returncode)
    except Exception as e:
        print(f"❌ Failed to run tests: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main() 