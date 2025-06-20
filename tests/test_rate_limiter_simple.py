#!/usr/bin/env python3
"""
Simplified rate limiter test for realistic conditions
Tests basic functionality without complex priority queues
"""

import asyncio
import time
import tempfile
import os
import sys
import random
from unittest.mock import patch, MagicMock

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.api_client import StickerdomAPI
from config import settings
from utils.logger import logger


class SimpleAPISimulator:
    """Simple API simulator for testing rate limits"""
    
    def __init__(self):
        self.request_count = 0
        self.rate_limit_remaining = 100
        self.rate_limit_reset_time = time.time() + 3600
        self.consecutive_429s = 0
        
    def simulate_request(self, **kwargs):
        """Simulate an API request with rate limiting"""
        self.request_count += 1
        current_time = time.time()
        
        # Simulate network delay
        time.sleep(random.uniform(0.05, 0.15))
        
        # Check if we should reset rate limit
        if current_time >= self.rate_limit_reset_time:
            self.rate_limit_remaining = 100
            self.rate_limit_reset_time = current_time + 3600
            self.consecutive_429s = 0
        
        # Simulate different scenarios based on request count
        scenario = self.request_count % 20
        
        if scenario <= 2:  # First few requests - normal
            if self.rate_limit_remaining > 0:
                self.rate_limit_remaining -= 1
                headers = {
                    'x-ratelimit-remaining': str(self.rate_limit_remaining),
                    'x-ratelimit-reset': str(int(self.rate_limit_reset_time)),
                    'etag': f'"etag-{self.request_count}"'
                }
                json_data = {'ok': True, 'data': {'test': f'response_{self.request_count}'}}
                return MockResponse(200, headers, json_data)
                
        elif scenario <= 5:  # Approaching limit
            if self.rate_limit_remaining > 3:
                self.rate_limit_remaining -= random.randint(2, 4)
                headers = {
                    'x-ratelimit-remaining': str(max(0, self.rate_limit_remaining)),
                    'x-ratelimit-reset': str(int(self.rate_limit_reset_time))
                }
                json_data = {'ok': True, 'data': {'test': f'response_{self.request_count}'}}
                return MockResponse(200, headers, json_data)
            else:
                # Hit rate limit
                self.consecutive_429s += 1
                headers = {
                    'x-ratelimit-remaining': '0',
                    'x-ratelimit-reset': str(int(self.rate_limit_reset_time)),
                    'retry-after': str(random.randint(60, 300))
                }
                return MockResponse(429, headers, {'ok': False, 'error': 'Rate limit exceeded'})
                
        elif scenario <= 10:  # Severe rate limiting (3600s scenario)
            self.consecutive_429s += 1
            headers = {
                'x-ratelimit-remaining': '0',
                'x-ratelimit-reset': str(int(current_time + 3600)),
                'retry-after': '3600'  # 1 hour retry
            }
            return MockResponse(429, headers, {'ok': False, 'error': 'Rate limit exceeded - severe'})
            
        else:  # Recovery phase
            if self.consecutive_429s >= 3:
                # Still rate limited but shorter delays
                headers = {
                    'x-ratelimit-remaining': '0',
                    'x-ratelimit-reset': str(int(current_time + 1800)),
                    'retry-after': str(random.randint(300, 900))
                }
                return MockResponse(429, headers, {'ok': False, 'error': 'Rate limit exceeded'})
            else:
                # Gradually allow requests
                if random.random() < 0.7:  # 70% success
                    self.rate_limit_remaining = max(0, self.rate_limit_remaining - 1)
                    headers = {
                        'x-ratelimit-remaining': str(self.rate_limit_remaining),
                        'x-ratelimit-reset': str(int(self.rate_limit_reset_time))
                    }
                    json_data = {'ok': True, 'data': {'test': f'recovery_{self.request_count}'}}
                    return MockResponse(200, headers, json_data)
                else:
                    headers = {
                        'x-ratelimit-remaining': '0',
                        'x-ratelimit-reset': str(int(current_time + 300))
                    }
                    return MockResponse(429, headers, {'ok': False, 'error': 'Still limited'})


class MockResponse:
    """Mock HTTP response"""
    
    def __init__(self, status_code, headers, json_data):
        self.status_code = status_code
        self.headers = headers
        self._json_data = json_data
        self.text = str(json_data)
    
    def json(self):
        return self._json_data


async def test_basic_rate_limiting():
    """Test basic rate limiting functionality"""
    logger.info("🔧 Testing basic rate limiting...")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = os.path.join(temp_dir, "simple_test.db")
        simulator = SimpleAPISimulator()
        
        # Mock the session
        with patch('services.api_client.requests.Session') as mock_session_class:
            mock_session = MagicMock()
            mock_session_class.return_value = mock_session
            mock_session.headers = {}
            
            # Setup request mocking
            mock_session.get.side_effect = lambda url, **kwargs: simulator.simulate_request(**kwargs)
            mock_session.post.side_effect = lambda url, **kwargs: simulator.simulate_request(**kwargs)
            
            # Configure settings
            original_enabled = settings.rate_limiter_enabled
            original_db_path = settings.rate_limiter_db_path
            original_max_delay = settings.rate_limiter_max_delay
            
            settings.rate_limiter_enabled = True
            settings.rate_limiter_db_path = db_path
            settings.rate_limiter_max_delay = 5  # Limit to 5s for testing
            
            try:
                api_client = StickerdomAPI()
                
                # Test 1: Normal requests
                logger.info("📊 Phase 1: Normal requests")
                start_time = time.time()
                
                results = []
                for i in range(5):
                    try:
                        result = await api_client.test_connection()
                        results.append(result)
                        logger.info(f"Request {i+1}: {'✅' if result else '❌'}")
                    except Exception as e:
                        results.append(False)
                        logger.info(f"Request {i+1}: ❌ ({e})")
                
                phase1_time = time.time() - start_time
                success_rate = sum(results) / len(results) * 100
                logger.info(f"Phase 1 results: {success_rate:.1f}% success in {phase1_time:.2f}s")
                
                # Test 2: Burst requests to trigger rate limiting
                logger.info("💥 Phase 2: Burst requests (should trigger rate limiting)")
                start_time = time.time()
                
                # Create many concurrent requests
                tasks = [api_client.test_connection() for _ in range(15)]
                burst_results = await asyncio.gather(*tasks, return_exceptions=True)
                
                phase2_time = time.time() - start_time
                burst_success = sum(1 for r in burst_results if r is True)
                burst_errors = sum(1 for r in burst_results if isinstance(r, Exception))
                
                logger.info(f"Phase 2 results: {burst_success}/15 successful, {burst_errors} errors in {phase2_time:.2f}s")
                
                # Test 3: Check rate limiter metrics
                logger.info("📊 Phase 3: Rate limiter metrics")
                metrics = api_client.get_rate_limiter_metrics()
                
                if metrics:
                    logger.info("Rate limiter metrics:")
                    logger.info(f"  Remaining requests: {metrics['rate_limit_state']['remaining']}")
                    logger.info(f"  Circuit breaker active: {metrics['circuit_breaker_active']}")
                    logger.info(f"  Consecutive failures: {metrics['consecutive_failures']}")
                    logger.info(f"  Cache entries: {metrics['cache_entries']}")
                else:
                    logger.warning("No metrics available")
                
                # Test 4: Wait for rate limit recovery
                logger.info("⏳ Phase 4: Rate limit recovery test")
                
                # Wait a bit and try again
                await asyncio.sleep(2)
                
                recovery_results = []
                for i in range(3):
                    try:
                        result = await api_client.test_connection()
                        recovery_results.append(result)
                        await asyncio.sleep(0.5)
                    except Exception as e:
                        recovery_results.append(False)
                        logger.info(f"Recovery request {i+1}: ❌ ({e})")
                
                recovery_success = sum(recovery_results) / len(recovery_results) * 100
                logger.info(f"Recovery phase: {recovery_success:.1f}% success")
                
                # Final metrics
                final_metrics = api_client.get_rate_limiter_metrics()
                if final_metrics:
                    logger.info("Final metrics:")
                    logger.info(f"  Total API requests made: {simulator.request_count}")
                    logger.info(f"  Consecutive 429s: {simulator.consecutive_429s}")
                    logger.info(f"  Circuit breaker active: {final_metrics['circuit_breaker_active']}")
                
                await api_client.cleanup()
                
                # Overall assessment
                total_requests = len(results) + len(burst_results) + len(recovery_results)
                total_successful = sum(results) + burst_success + sum(recovery_results)
                overall_success = total_successful / total_requests * 100
                
                logger.info("🏁 Test Summary:")
                logger.info(f"  Total requests attempted: {total_requests}")
                logger.info(f"  Total successful: {total_successful}")
                logger.info(f"  Overall success rate: {overall_success:.1f}%")
                logger.info(f"  API calls made: {simulator.request_count}")
                
                # Success criteria: at least 50% success rate with proper rate limiting
                if overall_success >= 50 and simulator.consecutive_429s >= 2:
                    logger.info("✅ Rate limiter working correctly - handles limits while maintaining functionality")
                    return True
                else:
                    logger.warning("⚠️ Rate limiter may need tuning")
                    return False
                
            finally:
                settings.rate_limiter_enabled = original_enabled
                settings.rate_limiter_db_path = original_db_path
                settings.rate_limiter_max_delay = original_max_delay


async def test_3600s_scenario():
    """Test specific 3600s rate limit scenario"""
    logger.info("⏰ Testing 3600s rate limit scenario...")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = os.path.join(temp_dir, "3600s_test.db")
        
        # Create simulator that always returns 3600s rate limit
        def always_429(**kwargs):
            time.sleep(0.1)  # Network delay
            headers = {
                'x-ratelimit-remaining': '0',
                'x-ratelimit-reset': str(int(time.time() + 3600)),
                'retry-after': '3600'
            }
            return MockResponse(429, headers, {'ok': False, 'error': 'Rate limit exceeded'})
        
        with patch('services.api_client.requests.Session') as mock_session_class:
            mock_session = MagicMock()
            mock_session_class.return_value = mock_session
            mock_session.headers = {}
            mock_session.get.side_effect = always_429
            mock_session.post.side_effect = always_429
            
            original_enabled = settings.rate_limiter_enabled
            original_db_path = settings.rate_limiter_db_path
            original_max_delay = settings.rate_limiter_max_delay
            original_circuit_timeout = settings.rate_limiter_circuit_breaker_timeout
            
            settings.rate_limiter_enabled = True
            settings.rate_limiter_db_path = db_path
            settings.rate_limiter_max_delay = 10  # Limit to 10s for testing
            settings.rate_limiter_circuit_breaker_timeout = 5  # 5s circuit breaker
            
            try:
                api_client = StickerdomAPI()
                
                logger.info("🔴 Testing 3600s rate limit responses...")
                
                start_time = time.time()
                
                # Try several requests - should trigger circuit breaker
                tasks = [api_client.test_connection() for _ in range(5)]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                test_time = time.time() - start_time
                
                errors = sum(1 for r in results if isinstance(r, Exception))
                false_results = sum(1 for r in results if r is False)
                
                logger.info(f"⏰ 3600s test results:")
                logger.info(f"  Test time: {test_time:.2f}s")
                logger.info(f"  Exceptions: {errors}/5")
                logger.info(f"  False results: {false_results}/5")
                
                # Check metrics
                metrics = api_client.get_rate_limiter_metrics()
                if metrics:
                    logger.info(f"  Circuit breaker active: {metrics['circuit_breaker_active']}")
                    logger.info(f"  Consecutive failures: {metrics['consecutive_failures']}")
                    
                    if metrics['circuit_breaker_active'] or metrics['consecutive_failures'] >= 3:
                        logger.info("✅ System correctly detected and handled 3600s rate limits")
                        result = True
                    else:
                        logger.warning("⚠️ System may not be handling severe rate limits optimally")
                        result = False
                else:
                    logger.warning("⚠️ No metrics available")
                    result = False
                
                await api_client.cleanup()
                return result
                
            finally:
                settings.rate_limiter_enabled = original_enabled
                settings.rate_limiter_db_path = original_db_path
                settings.rate_limiter_max_delay = original_max_delay
                settings.rate_limiter_circuit_breaker_timeout = original_circuit_timeout


async def run_simple_tests():
    """Run simplified rate limiter tests"""
    logger.info("🚀 Starting Simplified Rate Limiter Tests")
    logger.info("=" * 60)
    
    tests = [
        ("Basic Rate Limiting", test_basic_rate_limiting),
        ("3600s Scenario", test_3600s_scenario),
    ]
    
    passed = 0
    failed = 0
    
    for test_name, test_func in tests:
        logger.info(f"🧪 Running {test_name}...")
        logger.info("-" * 50)
        
        try:
            start_time = time.time()
            result = await test_func()
            test_time = time.time() - start_time
            
            if result:
                passed += 1
                logger.info(f"✅ {test_name} PASSED in {test_time:.2f}s")
            else:
                failed += 1
                logger.error(f"❌ {test_name} FAILED")
                
        except Exception as e:
            failed += 1
            logger.error(f"❌ {test_name} FAILED with exception: {e}")
        
        logger.info("")
        await asyncio.sleep(1)
    
    logger.info("=" * 60)
    logger.info("🏁 Simplified Rate Limiter Tests Summary")
    logger.info("=" * 60)
    logger.info(f"Tests passed: {passed}")
    logger.info(f"Tests failed: {failed}")
    
    if passed == len(tests):
        logger.info("🎉 ALL SIMPLIFIED TESTS PASSED!")
        logger.info("Rate limiter basic functionality confirmed for realistic conditions")
    else:
        logger.warning(f"⚠️ {failed} tests failed - check implementation")
    
    logger.info("=" * 60)
    return passed == len(tests)


if __name__ == "__main__":
    asyncio.run(run_simple_tests()) 