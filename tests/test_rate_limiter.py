#!/usr/bin/env python3
"""
Rate limiter unit tests
Tests core functionality, persistence, and backoff logic
"""

import asyncio
import tempfile
import time
import os
import sys
import pytest
from unittest.mock import AsyncMock, patch
from pathlib import Path

# Configure pytest-asyncio
pytestmark = pytest.mark.asyncio

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.rate_limiter import RateLimiterService, RequestPriority, RateLimitState
from utils.logger import logger


async def test_rate_limiter_basic_functionality():
    """Test basic rate limiter functionality"""
    logger.info("🧪 Testing basic rate limiter functionality...")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = os.path.join(temp_dir, "test_rate_limiter.db")
        rate_limiter = RateLimiterService(db_path)
        
        # Test initial state
        assert rate_limiter.state.remaining == 1000
        assert not rate_limiter.state.is_exhausted
        
        # Test header updates
        headers = {
            'x-ratelimit-remaining': '50',
            'x-ratelimit-reset': str(time.time() + 3600),
            'retry-after': '10'
        }
        rate_limiter.update_from_headers(headers, 200)
        
        assert rate_limiter.state.remaining == 50
        assert rate_limiter.state.retry_after == 10
        
        logger.info("✅ Basic functionality test passed")
        return True


async def test_rate_limiter_circuit_breaker():
    """Test circuit breaker functionality"""
    logger.info("🧪 Testing circuit breaker...")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = os.path.join(temp_dir, "test_circuit_breaker.db")
        rate_limiter = RateLimiterService(db_path)
        
        # Simulate repeated 429 errors to trigger circuit breaker
        for i in range(3):
            rate_limiter.update_from_headers({}, 429)
        
        assert rate_limiter.circuit_breaker_until > time.time()
        assert rate_limiter.consecutive_failures == 3
        
        # Test circuit breaker reset on success
        rate_limiter.update_from_headers({}, 200)
        assert rate_limiter.consecutive_failures == 0
        
        logger.info("✅ Circuit breaker test passed")
        return True


async def test_rate_limiter_conditional_headers():
    """Test conditional request headers (ETag, Last-Modified)"""
    logger.info("🧪 Testing conditional headers...")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = os.path.join(temp_dir, "test_conditional.db")
        rate_limiter = RateLimiterService(db_path)
        
        test_url = "https://api.example.com/test"
        
        # Update cache headers
        response_headers = {
            'etag': '"abc123"',
            'last-modified': 'Wed, 25 Oct 2023 19:17:59 GMT'
        }
        rate_limiter.update_cache_headers(test_url, response_headers)
        
        # Get conditional headers
        conditional_headers = rate_limiter.get_conditional_headers(test_url)
        
        assert conditional_headers['If-None-Match'] == '"abc123"'
        assert conditional_headers['If-Modified-Since'] == 'Wed, 25 Oct 2023 19:17:59 GMT'
        
        logger.info("✅ Conditional headers test passed")
        return True


async def test_rate_limiter_backoff_calculation():
    """Test exponential backoff with jitter"""
    logger.info("🧪 Testing backoff calculation...")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = os.path.join(temp_dir, "test_backoff.db")
        rate_limiter = RateLimiterService(db_path)
        
        # Test normal exponential backoff
        delay1 = rate_limiter.calculate_backoff_delay(1)
        delay2 = rate_limiter.calculate_backoff_delay(2)
        delay3 = rate_limiter.calculate_backoff_delay(3)
        
        # 2^attempt * base_delay + jitter (0-10% of delay)
        assert 2.0 <= delay1 <= 2.3  # 2^1 + up to 10% jitter
        assert 4.0 <= delay2 <= 4.5  # 2^2 + up to 10% jitter  
        assert 8.0 <= delay3 <= 9.0  # 2^3 + up to 10% jitter
        
        # Test with retry-after header
        rate_limiter.state.retry_after = 30
        delay_retry = rate_limiter.calculate_backoff_delay(1)
        assert delay_retry == 30
        
        # Test max delay cap
        delay_max = rate_limiter.calculate_backoff_delay(20)
        assert delay_max <= 3600  # Should be capped at 1 hour
        
        logger.info("✅ Backoff calculation test passed")
        return True


async def test_rate_limiter_request_queue():
    """Test priority request queue"""
    logger.info("🧪 Testing request queue with priorities...")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = os.path.join(temp_dir, "test_queue.db")
        rate_limiter = RateLimiterService(db_path)
        
        # Mock requests with different priorities
        results = []
        
        async def critical_request():
            await asyncio.sleep(0.1)
            results.append("CRITICAL")
            return "critical_result"
        
        async def normal_request():
            await asyncio.sleep(0.1)
            results.append("NORMAL")
            return "normal_result"
        
        async def low_request():
            await asyncio.sleep(0.1)
            results.append("LOW")
            return "low_result"
        
        # Add requests in reverse priority order
        tasks = [
            rate_limiter.execute_with_rate_limit(low_request, RequestPriority.LOW),
            rate_limiter.execute_with_rate_limit(normal_request, RequestPriority.NORMAL),
            rate_limiter.execute_with_rate_limit(critical_request, RequestPriority.CRITICAL)
        ]
        
        # Wait for all to complete
        await asyncio.gather(*tasks)
        
        # Critical should be executed first despite being added last
        assert results[0] == "CRITICAL"
        
        logger.info("✅ Request queue test passed")
        return True


async def test_rate_limiter_persistence():
    """Test state persistence across restarts"""
    logger.info("🧪 Testing state persistence...")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = os.path.join(temp_dir, "test_persistence.db")
        
        # Create first instance and update state
        rate_limiter1 = RateLimiterService(db_path)
        rate_limiter1.state.remaining = 100
        rate_limiter1.state.reset_timestamp = time.time() + 1800
        rate_limiter1.etag_cache['test_url'] = '"test_etag"'
        rate_limiter1._save_state()
        
        # Create second instance - should load saved state
        rate_limiter2 = RateLimiterService(db_path)
        
        assert rate_limiter2.state.remaining == 100
        assert 'test_url' in rate_limiter2.etag_cache
        assert rate_limiter2.etag_cache['test_url'] == '"test_etag"'
        
        logger.info("✅ Persistence test passed")
        return True


async def test_rate_limiter_should_wait():
    """Test wait decision logic"""
    logger.info("🧪 Testing wait decision logic...")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = os.path.join(temp_dir, "test_wait.db")
        rate_limiter = RateLimiterService(db_path)
        
        # Test normal state - should not wait
        with patch('asyncio.sleep') as mock_sleep:
            should_wait = await rate_limiter.should_wait_before_request()
            assert not should_wait
            mock_sleep.assert_not_called()
        
        # Test low remaining - should wait
        rate_limiter.state.remaining = 5
        with patch('asyncio.sleep') as mock_sleep:
            should_wait = await rate_limiter.should_wait_before_request()
            assert should_wait
            mock_sleep.assert_called_once()
        
        # Test circuit breaker - should wait
        rate_limiter.circuit_breaker_until = time.time() + 10
        with patch('asyncio.sleep') as mock_sleep:
            should_wait = await rate_limiter.should_wait_before_request()
            assert should_wait
            mock_sleep.assert_called_once()
        
        logger.info("✅ Wait decision test passed")
        return True


async def test_rate_limiter_metrics():
    """Test metrics collection"""
    logger.info("🧪 Testing metrics collection...")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = os.path.join(temp_dir, "test_metrics.db")
        rate_limiter = RateLimiterService(db_path)
        
        # Update some state
        rate_limiter.state.remaining = 42
        rate_limiter.consecutive_failures = 2
        rate_limiter.etag_cache['test'] = '"etag"'
        
        metrics = rate_limiter.get_metrics()
        
        assert metrics['rate_limit_state']['remaining'] == 42
        assert metrics['consecutive_failures'] == 2
        assert metrics['cache_entries'] == 1
        assert 'circuit_breaker_active' in metrics
        assert 'queue_size' in metrics
        
        logger.info("✅ Metrics test passed")
        return True


async def run_all_rate_limiter_tests():
    """Run all rate limiter tests"""
    logger.info("🚀 Starting rate limiter tests...")
    
    tests = [
        test_rate_limiter_basic_functionality,
        test_rate_limiter_circuit_breaker,
        test_rate_limiter_conditional_headers,
        test_rate_limiter_backoff_calculation,
        test_rate_limiter_request_queue,
        test_rate_limiter_persistence,
        test_rate_limiter_should_wait,
        test_rate_limiter_metrics
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            result = await test()
            if result:
                passed += 1
            else:
                failed += 1
                logger.error(f"❌ Test {test.__name__} failed")
        except Exception as e:
            failed += 1
            logger.error(f"❌ Test {test.__name__} failed with exception: {e}")
        
        # Small delay between tests
        await asyncio.sleep(0.1)
    
    logger.info(f"🏁 Rate limiter tests completed: {passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    import asyncio
    asyncio.run(run_all_rate_limiter_tests()) 