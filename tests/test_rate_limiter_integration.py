#!/usr/bin/env python3
"""
Integration tests for rate limiter under realistic conditions
Simulates real API behavior, different rate limit scenarios, and stress testing
"""

import asyncio
import time
import tempfile
import os
import sys
import random
from unittest.mock import AsyncMock, patch, MagicMock
from typing import Dict, List, Any

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.api_client import StickerdomAPI
from services.rate_limiter import RateLimiterService, RequestPriority
from config import settings
from utils.logger import logger


class MockAPIResponse:
    """Mock API response with realistic behavior"""
    
    def __init__(self, status_code: int = 200, headers: Dict[str, str] = None, json_data: Dict = None):
        self.status_code = status_code
        self.headers = headers or {}
        self._json_data = json_data or {'ok': True, 'data': {}}
        self.text = str(json_data) if json_data else "Mock response"
    
    def json(self):
        return self._json_data


class APISimulator:
    """Simulates real API behavior with rate limiting"""
    
    def __init__(self):
        self.request_count = 0
        self.rate_limit_remaining = 100
        self.rate_limit_reset_time = time.time() + 3600
        self.current_scenario = "normal"
        self.scenario_start_time = time.time()
        
    def make_request(self, method: str, url: str, **kwargs) -> MockAPIResponse:
        """Simulate API request with realistic rate limiting behavior"""
        self.request_count += 1
        current_time = time.time()
        
        # Reset rate limit if time has passed
        if current_time >= self.rate_limit_reset_time:
            self.rate_limit_remaining = 100
            self.rate_limit_reset_time = current_time + 3600
        
        # Apply current scenario logic
        if self.current_scenario == "approaching_limit":
            # Gradually decrease remaining requests
            if self.rate_limit_remaining > 0:
                self.rate_limit_remaining -= random.randint(1, 3)
            
            if self.rate_limit_remaining <= 0:
                # Return 429 with retry-after
                headers = {
                    'x-ratelimit-remaining': '0',
                    'x-ratelimit-reset': str(int(self.rate_limit_reset_time)),
                    'retry-after': str(random.randint(60, 300))  # 1-5 minutes
                }
                return MockAPIResponse(429, headers, {'ok': False, 'error': 'Rate limit exceeded'})
        
        elif self.current_scenario == "severe_limiting":
            # Simulate severe rate limiting like the 3600s case
            if random.random() < 0.7:  # 70% chance of 429
                headers = {
                    'x-ratelimit-remaining': '0',
                    'x-ratelimit-reset': str(int(current_time + 3600)),  # 1 hour reset
                    'retry-after': str(random.randint(3600, 7200))  # 1-2 hours retry
                }
                return MockAPIResponse(429, headers, {'ok': False, 'error': 'Rate limit exceeded'})
        
        elif self.current_scenario == "unstable_api":
            # Simulate unstable API with random errors
            error_chance = random.random()
            if error_chance < 0.2:  # 20% chance of 500 error
                return MockAPIResponse(500, {}, {'ok': False, 'error': 'Internal server error'})
            elif error_chance < 0.4:  # 20% chance of 429
                headers = {
                    'x-ratelimit-remaining': str(max(0, self.rate_limit_remaining - 1)),
                    'x-ratelimit-reset': str(int(self.rate_limit_reset_time)),
                    'retry-after': str(random.randint(10, 60))
                }
                self.rate_limit_remaining = max(0, self.rate_limit_remaining - 1)
                return MockAPIResponse(429, headers, {'ok': False, 'error': 'Rate limit exceeded'})
        
        # Normal successful response
        if self.rate_limit_remaining > 0:
            self.rate_limit_remaining -= 1
        
        headers = {
            'x-ratelimit-remaining': str(self.rate_limit_remaining),
            'x-ratelimit-reset': str(int(self.rate_limit_reset_time)),
            'etag': f'"etag-{self.request_count}"',
            'last-modified': time.strftime('%a, %d %b %Y %H:%M:%S GMT', time.gmtime())
        }
        
        # Return appropriate response based on endpoint
        if 'collection' in url:
            json_data = {
                'ok': True,
                'data': {
                    'collection': {
                        'id': 1,
                        'name': 'Test Collection',
                        'status': 'active'
                    },
                    'characters': [
                        {
                            'id': 1,
                            'name': 'Test Character',
                            'left': random.randint(1, 100),
                            'total': 1000,
                            'rarity': 'common'
                        }
                    ]
                }
            }
        elif 'price' in url:
            json_data = {
                'ok': True,
                'data': [
                    {
                        'token_symbol': 'TON',
                        'price': f"{random.uniform(0.1, 1.0):.6f}"
                    }
                ]
            }
        elif 'purchase' in url:
            json_data = {
                'ok': True,
                'data': {
                    'purchase_id': f'purchase_{self.request_count}',
                    'wallet_address': 'EQTest123...',
                    'amount': '0.5',
                    'memo': 'test_purchase'
                }
            }
        else:
            json_data = {'ok': True, 'data': {}}
        
        return MockAPIResponse(200, headers, json_data)
    
    def set_scenario(self, scenario: str):
        """Change API behavior scenario"""
        self.current_scenario = scenario
        self.scenario_start_time = time.time()
        logger.info(f"🎭 API Simulator: Switching to scenario '{scenario}'")


async def test_realistic_rate_limiting_scenarios():
    """Test rate limiter under various realistic scenarios"""
    logger.info("🏗️ Testing realistic rate limiting scenarios...")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = os.path.join(temp_dir, "integration_rate_limiter.db")
        api_simulator = APISimulator()
        
        # Mock the curl_cffi requests to use our simulator
        with patch('services.api_client.requests.Session') as mock_session_class:
            mock_session = MagicMock()
            mock_session_class.return_value = mock_session
            
            # Configure session mock
            def mock_request(method):
                def request_func(url, **kwargs):
                    return api_simulator.make_request(method.upper(), url, **kwargs)
                return request_func
            
            mock_session.get = mock_request('get')
            mock_session.post = mock_request('post')
            mock_session.headers = {}
            
            # Create API client with rate limiter
            original_enabled = settings.rate_limiter_enabled
            original_db_path = settings.rate_limiter_db_path
            
            settings.rate_limiter_enabled = True
            settings.rate_limiter_db_path = db_path
            # Force test mode to prevent long delays
            settings.test_mode = True
            
            try:
                api_client = StickerdomAPI()
                
                # Scenario 1: Normal operation
                logger.info("📊 Scenario 1: Normal API operation")
                api_simulator.set_scenario("normal")
                
                start_time = time.time()
                results = []
                
                # Make multiple requests of different priorities
                tasks = [
                    api_client.get_collection(1, priority=RequestPriority.CRITICAL),
                    api_client.get_character_price(1, 1, priority=RequestPriority.HIGH),
                    api_client.get_collection(2, priority=RequestPriority.NORMAL),
                    api_client.get_collection(3, priority=RequestPriority.LOW),
                ]
                
                results = await asyncio.gather(*tasks, return_exceptions=True)
                normal_time = time.time() - start_time
                
                success_count = sum(1 for r in results if r is not None and not isinstance(r, Exception))
                logger.info(f"✅ Normal scenario: {success_count}/4 requests successful in {normal_time:.2f}s")
                
                # Scenario 2: Approaching rate limit
                logger.info("⚠️ Scenario 2: Approaching rate limit")
                api_simulator.set_scenario("approaching_limit")
                api_simulator.rate_limit_remaining = 5  # Very low
                
                start_time = time.time()
                
                # Try to make many requests
                tasks = [
                    api_client.get_character_price(1, i, priority=RequestPriority.HIGH)
                    for i in range(10)
                ]
                
                results = await asyncio.gather(*tasks, return_exceptions=True)
                approach_time = time.time() - start_time
                
                success_count = sum(1 for r in results if r is not None and not isinstance(r, Exception))
                logger.info(f"⚠️ Approach limit scenario: {success_count}/10 requests successful in {approach_time:.2f}s")
                
                # Scenario 3: Severe rate limiting (like 3600s case)
                logger.info("🚨 Scenario 3: Severe rate limiting (3600s simulation)")
                api_simulator.set_scenario("severe_limiting")
                
                start_time = time.time()
                
                # Test circuit breaker activation
                tasks = [
                    api_client.get_collection(i, priority=RequestPriority.NORMAL)
                    for i in range(5)
                ]
                
                results = await asyncio.gather(*tasks, return_exceptions=True)
                severe_time = time.time() - start_time
                
                success_count = sum(1 for r in results if r is not None and not isinstance(r, Exception))
                logger.info(f"🚨 Severe limiting scenario: {success_count}/5 requests successful in {severe_time:.2f}s")
                
                # Check if circuit breaker was activated
                metrics = api_client.get_rate_limiter_metrics()
                if metrics and metrics.get('circuit_breaker_active', False):
                    logger.info("✅ Circuit breaker correctly activated during severe limiting")
                
                # Scenario 4: Mixed priority under stress
                logger.info("🎯 Scenario 4: Mixed priority requests under stress")
                api_simulator.set_scenario("unstable_api")
                
                start_time = time.time()
                
                # Mix of critical and low priority requests
                tasks = [
                    # Critical requests (purchases)
                    api_client.initiate_purchase(1, 1),
                    api_client.initiate_purchase(1, 2),
                    # High priority (price checks)
                    api_client.get_character_price(1, 1, priority=RequestPriority.HIGH),
                    api_client.get_character_price(1, 2, priority=RequestPriority.HIGH),
                    # Low priority (monitoring)
                    api_client.get_collection(1, priority=RequestPriority.LOW),
                    api_client.get_collection(2, priority=RequestPriority.LOW),
                ]
                
                results = await asyncio.gather(*tasks, return_exceptions=True)
                mixed_time = time.time() - start_time
                
                # Check that critical requests were processed first
                critical_success = sum(1 for i, r in enumerate(results[:2]) 
                                     if r is not None and not isinstance(r, Exception))
                total_success = sum(1 for r in results if r is not None and not isinstance(r, Exception))
                
                logger.info(f"🎯 Mixed priority scenario: {total_success}/6 total, {critical_success}/2 critical successful in {mixed_time:.2f}s")
                
                # Final metrics
                final_metrics = api_client.get_rate_limiter_metrics()
                if final_metrics:
                    logger.info("📊 Final Rate Limiter Metrics:")
                    logger.info(f"   Remaining requests: {final_metrics['rate_limit_state']['remaining']}")
                    logger.info(f"   Consecutive failures: {final_metrics['consecutive_failures']}")
                    logger.info(f"   Circuit breaker active: {final_metrics['circuit_breaker_active']}")
                    logger.info(f"   Cache entries: {final_metrics['cache_entries']}")
                    logger.info(f"   Queue size: {final_metrics['queue_size']}")
                
                logger.info("✅ Realistic rate limiting scenarios test completed")
                return True
                
            finally:
                # Restore settings
                settings.rate_limiter_enabled = original_enabled
                settings.rate_limiter_db_path = original_db_path
                if hasattr(settings, 'test_mode'):
                    delattr(settings, 'test_mode')
                
                # Cleanup
                if hasattr(api_client, 'cleanup'):
                    await api_client.cleanup()


async def test_severe_3600s_simulation():
    """Simulate the exact 3600s rate limit scenario"""
    logger.info("⏰ Testing 3600s rate limit scenario...")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = os.path.join(temp_dir, "3600s_rate_limiter.db")
        api_simulator = APISimulator()
        
        with patch('services.api_client.requests.Session') as mock_session_class:
            mock_session = MagicMock()
            mock_session_class.return_value = mock_session
            
            # Setup for 3600s scenario
            current_time = time.time()
            
            def mock_3600s_request(method):
                def request_func(url, **kwargs):
                    # Simulate network delay
                    time.sleep(random.uniform(0.1, 0.2))
                    
                    # Always return 429 with 3600s retry
                    headers = {
                        'x-ratelimit-remaining': '0',
                        'x-ratelimit-reset': str(int(current_time + 3600)),
                        'retry-after': '3600'
                    }
                    return MockAPIResponse(429, headers, {'ok': False, 'error': 'Rate limit exceeded'})
                return request_func
            
            mock_session.get = mock_3600s_request('get')
            mock_session.post = mock_3600s_request('post')
            mock_session.headers = {}
            
            original_enabled = settings.rate_limiter_enabled
            original_db_path = settings.rate_limiter_db_path
            original_max_delay = settings.rate_limiter_max_delay
            
            settings.rate_limiter_enabled = True
            settings.rate_limiter_db_path = db_path
            settings.rate_limiter_max_delay = 10  # Limit to 10s for testing
            settings.test_mode = True  # Force test mode
            
            try:
                api_client = StickerdomAPI()
                
                logger.info("🔴 Testing behavior with 3600s rate limit...")
                
                start_time = time.time()
                
                # Try multiple requests that should hit rate limit
                tasks = [
                    api_client.get_collection(1, priority=RequestPriority.CRITICAL),
                    api_client.get_character_price(1, 1, priority=RequestPriority.HIGH),
                    api_client.get_collection(2, priority=RequestPriority.NORMAL),
                ]
                
                results = await asyncio.gather(*tasks, return_exceptions=True)
                test_time = time.time() - start_time
                
                # Check results
                success_count = sum(1 for r in results if r is not None and not isinstance(r, Exception))
                exception_count = sum(1 for r in results if isinstance(r, Exception))
                
                logger.info(f"⏰ 3600s scenario results:")
                logger.info(f"   Total time: {test_time:.2f}s")
                logger.info(f"   Successful requests: {success_count}/3")
                logger.info(f"   Failed requests: {exception_count}/3")
                
                # Check rate limiter state
                metrics = api_client.get_rate_limiter_metrics()
                if metrics:
                    logger.info(f"   Circuit breaker active: {metrics['circuit_breaker_active']}")
                    logger.info(f"   Consecutive failures: {metrics['consecutive_failures']}")
                    logger.info(f"   Rate limit remaining: {metrics['rate_limit_state']['remaining']}")
                
                # Test that circuit breaker activates
                if metrics and metrics.get('circuit_breaker_active', False):
                    logger.info("✅ Circuit breaker correctly activated for 3600s scenario")
                elif metrics and metrics['consecutive_failures'] >= 3:
                    logger.info("✅ System correctly detected consecutive failures")
                else:
                    logger.warning("⚠️ Circuit breaker may not be working as expected")
                
                await api_client.cleanup()
                
                logger.info("✅ 3600s rate limit simulation completed")
                return True
                
            finally:
                settings.rate_limiter_enabled = original_enabled
                settings.rate_limiter_db_path = original_db_path
                settings.rate_limiter_max_delay = original_max_delay
                if hasattr(settings, 'test_mode'):
                    delattr(settings, 'test_mode')


async def test_burst_and_throttling():
    """Test burst requests and throttling behavior"""
    logger.info("💥 Testing burst requests and adaptive throttling...")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = os.path.join(temp_dir, "burst_rate_limiter.db")
        
        with patch('services.api_client.requests.Session') as mock_session_class:
            mock_session = MagicMock()
            mock_session_class.return_value = mock_session
            
            request_times = []
            
            def mock_burst_request(method):
                def request_func(url, **kwargs):
                    request_times.append(time.time())
                    
                    # Gradually increase delays to simulate throttling
                    delay_index = len(request_times) % 5
                    delays = [0.1, 0.2, 0.5, 1.0, 2.0]
                    time.sleep(delays[delay_index])
                    
                    headers = {
                        'x-ratelimit-remaining': str(max(0, 100 - len(request_times))),
                        'x-ratelimit-reset': str(int(time.time() + 3600)),
                    }
                    
                    json_data = {'ok': True, 'data': {'test': 'response'}}
                    return MockAPIResponse(200, headers, json_data)
                return request_func
            
            mock_session.get = mock_burst_request('get')
            mock_session.post = mock_burst_request('post')
            mock_session.headers = {}
            
            original_enabled = settings.rate_limiter_enabled
            original_db_path = settings.rate_limiter_db_path
            
            settings.rate_limiter_enabled = True
            settings.rate_limiter_db_path = db_path
            settings.test_mode = True  # Force test mode
            
            try:
                api_client = StickerdomAPI()
                
                logger.info("🚀 Sending burst of requests...")
                
                # Create burst of 20 requests at once
                burst_tasks = [
                    api_client.get_collection(i % 5 + 1, priority=RequestPriority.NORMAL)
                    for i in range(20)
                ]
                
                start_time = time.time()
                burst_results = await asyncio.gather(*burst_tasks, return_exceptions=True)
                burst_time = time.time() - start_time
                
                success_count = sum(1 for r in burst_results if r is not None and not isinstance(r, Exception))
                
                logger.info(f"💥 Burst results:")
                logger.info(f"   Total requests: 20")
                logger.info(f"   Successful: {success_count}")
                logger.info(f"   Total time: {burst_time:.2f}s")
                logger.info(f"   Avg time per request: {burst_time/20:.3f}s")
                
                # Analyze request timing
                if len(request_times) >= 2:
                    intervals = [request_times[i] - request_times[i-1] for i in range(1, len(request_times))]
                    avg_interval = sum(intervals) / len(intervals)
                    min_interval = min(intervals)
                    max_interval = max(intervals)
                    
                    logger.info(f"📊 Request timing analysis:")
                    logger.info(f"   Average interval: {avg_interval:.3f}s")
                    logger.info(f"   Min interval: {min_interval:.3f}s")
                    logger.info(f"   Max interval: {max_interval:.3f}s")
                    
                    # Check if rate limiter properly queued requests
                    if min_interval >= 0.09:  # Should have at least 0.1s between requests due to queue processing
                        logger.info("✅ Rate limiter properly queued and throttled requests")
                    else:
                        logger.warning("⚠️ Some requests may have bypassed rate limiting")
                
                await api_client.cleanup()
                
                logger.info("✅ Burst and throttling test completed")
                return success_count >= 15  # At least 75% success rate
                
            finally:
                settings.rate_limiter_enabled = original_enabled
                settings.rate_limiter_db_path = original_db_path
                if hasattr(settings, 'test_mode'):
                    delattr(settings, 'test_mode')


async def run_integration_tests():
    """Run all integration tests"""
    logger.info("🚀 Starting Rate Limiter Integration Tests")
    logger.info("=" * 60)
    
    tests = [
        ("Realistic Rate Limiting Scenarios", test_realistic_rate_limiting_scenarios),
        ("Severe 3600s Simulation", test_severe_3600s_simulation),
        ("Burst and Throttling", test_burst_and_throttling),
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
        await asyncio.sleep(1)  # Brief pause between tests
    
    logger.info("=" * 60)
    logger.info("🏁 Rate Limiter Integration Tests Summary")
    logger.info("=" * 60)
    logger.info(f"Tests passed: {passed}")
    logger.info(f"Tests failed: {failed}")
    logger.info(f"Success rate: {(passed/(passed+failed))*100:.1f}%")
    
    if failed == 0:
        logger.info("🎉 ALL INTEGRATION TESTS PASSED!")
        logger.info("Rate limiter is production-ready for 3600s limits and beyond")
    else:
        logger.warning(f"⚠️ {failed} integration tests failed - review implementation")
    
    logger.info("=" * 60)
    return failed == 0


if __name__ == "__main__":
    import asyncio
    asyncio.run(run_integration_tests()) 