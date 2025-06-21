#!/usr/bin/env python3
"""
API Connection Test
"""

import asyncio
import sys
import os
import pytest

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.api_client import StickerdomAPI
from config import settings
from utils.logger import logger


@pytest.mark.asyncio
async def test_api_connection():
    """Test API connection"""
    logger.info("🌐 Testing API connection...")
    
    api = StickerdomAPI()
    result = await api.test_connection()
    
    if result:
        logger.info("✅ API connection test PASSED")
    else:
        logger.error("❌ API connection test FAILED")
    
    return result


@pytest.mark.asyncio
async def test_api_collection(collection_id: int = 1):
    """Test collection retrieval"""
    logger.info(f"📦 Testing collection retrieval for ID {collection_id}...")
    
    api = StickerdomAPI()
    collection = await api.get_collection(collection_id)
    
    if collection:
        logger.info(f"✅ Collection test PASSED: {collection.name}")
        logger.info(f"   Characters: {len(collection.characters)}")
        logger.info(f"   Status: {collection.status}")
    else:
        logger.warning(f"⚠️ Collection {collection_id} not found or unavailable")
    
    return collection is not None


@pytest.mark.asyncio
async def test_api_price(collection_id: int = 1, character_id: int = 1):
    """Test price retrieval"""
    logger.info(f"💰 Testing price retrieval for {collection_id}/{character_id}...")
    
    api = StickerdomAPI()
    price = await api.get_character_price(collection_id, character_id)
    
    if price is not None:
        logger.info(f"✅ Price test PASSED: {price} TON")
    else:
        logger.warning(f"⚠️ Price not available for {collection_id}/{character_id}")
    
    return price is not None


async def run_all_api_tests():
    """Run all API tests"""
    logger.info("🧪 Starting API Tests")
    logger.info("=" * 50)
    
    tests_passed = 0
    total_tests = 3
    
    # Test connection
    if await test_api_connection():
        tests_passed += 1
    
    # Test collection
    if await test_api_collection():
        tests_passed += 1
    
    # Test price
    if await test_api_price():
        tests_passed += 1
    
    logger.info("=" * 50)
    logger.info(f"API Tests completed: {tests_passed}/{total_tests} passed")
    
    if tests_passed == total_tests:
        logger.info("✅ All API tests PASSED!")
    else:
        logger.warning(f"⚠️ {total_tests - tests_passed} API tests FAILED")
    
    return tests_passed == total_tests


if __name__ == "__main__":
    asyncio.run(run_all_api_tests()) 