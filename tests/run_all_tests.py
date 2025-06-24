#!/usr/bin/env python3
"""
Run All Tests - comprehensive test suite
"""

import asyncio
import subprocess
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.logger import logger


def run_subprocess_test(script_name: str, description: str) -> bool:
    """Run a test script as subprocess"""
    logger.info(f"🧪 Running {description}...")
    logger.info("=" * 50)
    
    try:
        result = subprocess.run([sys.executable, script_name], 
                              capture_output=False, 
                              text=True, 
                              timeout=300)  # 5 minute timeout
        
        if result.returncode == 0:
            logger.info(f"✅ {description} PASSED")
            return True
        else:
            logger.error(f"❌ {description} FAILED (exit code: {result.returncode})")
            return False
            
    except subprocess.TimeoutExpired:
        logger.error(f"❌ {description} FAILED (timeout)")
        return False
    except Exception as e:
        logger.error(f"❌ {description} FAILED (error: {e})")
        return False


async def run_main_py_tests():
    """Run main.py test modes"""
    logger.info("🧪 Running main.py test modes...")
    logger.info("=" * 50)
    
    tests_passed = 0
    total_tests = 1
    
    # Test configuration and connections
    try:
        result = subprocess.run([sys.executable, "main.py", "1/1", "--test"], 
                              capture_output=False, 
                              text=True, 
                              timeout=60)
        if result.returncode == 0:
            logger.info("✅ Main.py test mode PASSED")
            tests_passed += 1
        else:
            logger.error("❌ Main.py test mode FAILED")
    except Exception as e:
        logger.error(f"❌ Main.py test mode FAILED: {e}")
    
    logger.info(f"Main.py tests: {tests_passed}/{total_tests} passed")
    return tests_passed == total_tests


async def run_all_tests():
    """Run complete test suite"""
    logger.info("🚀 Starting Complete Test Suite")
    logger.info("=" * 60)
    
    tests_passed = 0
    total_test_suites = 5
    
    # 1. Captcha Tests
    if run_subprocess_test("tests/test_captcha.py", "Captcha System Tests"):
        tests_passed += 1
    
    # 2. API Tests
    if run_subprocess_test("tests/test_api.py", "API Connection Tests"):
        tests_passed += 1
    
    # 3. Wallet Tests
    if run_subprocess_test("tests/test_wallet.py", "TON Wallet Tests"):
        tests_passed += 1
    
    # 4. Main.py Tests
    if await run_main_py_tests():
        tests_passed += 1
    
    # 5. Basic Import Tests
    logger.info("🧪 Running Import Tests...")
    logger.info("=" * 50)
    try:
        # Test all critical imports
        from config import settings
        from services.api_client import StickerdomAPI
        from services.ton_wallet import TONWalletManager
        from services.captcha_solver import CaptchaManager
        
        logger.info("✅ All critical imports (config, API, wallet, captcha) successful")
        tests_passed += 1
    except Exception as e:
        logger.error(f"❌ Import tests failed: {e}")
    
    # Summary
    logger.info("=" * 60)
    logger.info("🏁 TEST SUITE COMPLETED")
    logger.info("=" * 60)
    logger.info(f"Test Suites Passed: {tests_passed}/{total_test_suites}")
    
    if tests_passed == total_test_suites:
        logger.info("🎉 ALL TESTS PASSED! Project is ready to use.")
    elif tests_passed >= total_test_suites * 0.8:  # 80% success rate
        logger.warning(f"⚠️ Most tests passed ({tests_passed}/{total_test_suites}). Check failed tests.")
    else:
        logger.error(f"❌ Many tests failed ({total_test_suites - tests_passed}/{total_test_suites}). Review configuration.")
    
    logger.info("=" * 60)
    
    return tests_passed == total_test_suites


if __name__ == "__main__":
    print("🧪 TG Stickers Auto-Mint Test Suite")
    print("=" * 60)
    
    # Run all tests
    success = asyncio.run(run_all_tests())
    
    # Exit with appropriate code
    sys.exit(0 if success else 1) 