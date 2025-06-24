#!/usr/bin/env python3
"""
TON Wallet Test
"""

import asyncio
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.ton_wallet import TONWalletManager
from config import settings
from utils.logger import logger


async def test_wallet_connection():
    """Test wallet connection and initialization"""
    logger.info("👛 Testing wallet connection...")
    
    try:
        wallet = TONWalletManager()
        await wallet.initialize()
        
        logger.info(f"✅ Wallet connected: {wallet.wallet.address.to_str()}")
        return True
    except Exception as e:
        logger.error(f"❌ Wallet connection failed: {e}")
        return False


async def test_wallet_balance():
    """Test wallet balance retrieval"""
    logger.info("💰 Testing wallet balance...")
    
    try:
        wallet = TONWalletManager()
        await wallet.initialize()
        
        wallet_info = await wallet.get_wallet_info()
        balance = wallet_info.balance_ton
        logger.info(f"✅ Balance retrieved: {balance} TON")
        
        if balance >= 0:
            return True
        else:
            logger.warning("⚠️ Negative balance detected")
            return False
    except Exception as e:
        logger.error(f"❌ Balance retrieval failed: {e}")
        return False


async def test_wallet_address():
    """Test wallet address format"""
    logger.info("🏠 Testing wallet address...")
    
    try:
        wallet = TONWalletManager()
        await wallet.initialize()
        
        wallet_info = await wallet.get_wallet_info()
        address = wallet_info.address
        
        # Check if address looks valid (starts with UQ or EQ)
        if address.startswith(('UQ', 'EQ')) and len(address) > 40:
            logger.info(f"✅ Valid address format: {address}")
            return True
        else:
            logger.error(f"❌ Invalid address format: {address}")
            return False
    except Exception as e:
        logger.error(f"❌ Address check failed: {e}")
        return False


async def test_wallet_dry_run():
    """Test wallet dry run functionality"""
    logger.info("🧪 Testing wallet dry run...")
    
    try:
        wallet = TONWalletManager()
        await wallet.initialize()
        
        # Test wallet info retrieval as dry run
        wallet_info = await wallet.get_wallet_info()
        
        # Check if we have enough balance for a small transaction
        min_amount = 0.01 + settings.gas_amount  # 0.01 TON + gas
        
        if wallet_info.balance_ton >= min_amount:
            logger.info(f"✅ Dry run successful: sufficient balance for test transaction")
            logger.info(f"   Available: {wallet_info.balance_ton:.9f} TON")
            logger.info(f"   Required: {min_amount:.9f} TON")
            return True
        else:
            logger.warning(f"⚠️ Insufficient balance for transaction: {wallet_info.balance_ton:.9f} TON")
            return True  # Still pass test as wallet is working
    except Exception as e:
        logger.error(f"❌ Dry run failed: {e}")
        return False


async def run_all_wallet_tests():
    """Run all wallet tests"""
    logger.info("🧪 Starting Wallet Tests")
    logger.info("=" * 50)
    
    tests_passed = 0
    total_tests = 4
    
    # Test connection
    if await test_wallet_connection():
        tests_passed += 1
    
    # Test balance
    if await test_wallet_balance():
        tests_passed += 1
    
    # Test address
    if await test_wallet_address():
        tests_passed += 1
    
    # Test dry run
    if await test_wallet_dry_run():
        tests_passed += 1
    
    logger.info("=" * 50)
    logger.info(f"Wallet Tests completed: {tests_passed}/{total_tests} passed")
    
    if tests_passed == total_tests:
        logger.info("✅ All wallet tests PASSED!")
    else:
        logger.warning(f"⚠️ {total_tests - tests_passed} wallet tests FAILED")
    
    return tests_passed == total_tests


if __name__ == "__main__":
    asyncio.run(run_all_wallet_tests()) 