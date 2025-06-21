#!/usr/bin/env python3
"""
Endpoint Discovery System
Uses Selenium to discover current API endpoints by monitoring browser network traffic
"""

import asyncio
import json
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import TimeoutException, WebDriverException

from utils.logger import logger
from config import settings


@dataclass
class DiscoveredEndpoint:
    """Discovered API endpoint information"""
    url: str
    method: str
    parameters: Dict[str, Any]
    headers: Dict[str, str]
    response_status: int
    timestamp: datetime
    operation_type: str  # 'purchase_ton', 'purchase_stars', 'collection', etc.


@dataclass
class EndpointPattern:
    """Pattern for endpoint validation"""
    base_url: str
    required_params: List[str]
    optional_params: List[str]
    method: str
    operation_type: str


class NetworkTrafficMonitor:
    """Monitors browser network traffic to capture API calls"""
    
    def __init__(self):
        self.driver = None
        self.captured_requests = []
        self.is_monitoring = False
        
    def setup_driver(self) -> webdriver.Chrome:
        """Setup Chrome driver with network monitoring capabilities"""
        chrome_options = Options()
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--window-size=1920,1080')
        
        # Enable performance logging for network capture
        chrome_options.add_argument('--enable-logging')
        chrome_options.add_argument('--log-level=0')
        chrome_options.set_capability('goog:loggingPrefs', {'performance': 'ALL'})
        
        # Run headless for production
        if not settings.selenium_headless_disabled:
            chrome_options.add_argument('--headless')
            
        try:
            self.driver = webdriver.Chrome(options=chrome_options)
            self.driver.execute_cdp_cmd('Network.enable', {})
            self.driver.execute_cdp_cmd('Page.enable', {})
            logger.info("Chrome driver initialized for network monitoring")
            return self.driver
        except Exception as e:
            logger.error(f"Failed to setup Chrome driver: {e}")
            raise
    
    def start_monitoring(self):
        """Start capturing network requests"""
        if not self.driver:
            self.setup_driver()
        
        self.captured_requests = []
        self.is_monitoring = True
        logger.info("Started network traffic monitoring")
    
    def stop_monitoring(self) -> List[Dict]:
        """Stop monitoring and return captured requests"""
        self.is_monitoring = False
        
        if not self.driver:
            return []
        
        # Get performance logs
        logs = self.driver.get_log('performance')
        network_requests = []
        
        for log in logs:
            try:
                message = json.loads(log['message'])
                if message['message']['method'] in ['Network.responseReceived', 'Network.requestWillBeSent']:
                    network_requests.append(message['message'])
            except (json.JSONDecodeError, KeyError):
                continue
        
        logger.info(f"Captured {len(network_requests)} network requests")
        return network_requests
    
    def cleanup(self):
        """Clean up resources"""
        if self.driver:
            try:
                self.driver.quit()
                self.driver = None
                logger.info("Chrome driver cleaned up")
            except Exception as e:
                logger.warning(f"Error cleaning up driver: {e}")


class EndpointDiscovery:
    """Main endpoint discovery service using Selenium"""
    
    def __init__(self):
        self.monitor = NetworkTrafficMonitor()
        self.known_patterns = self._load_known_patterns()
        self.discovered_endpoints = {}
        
    def _load_known_patterns(self) -> Dict[str, List[EndpointPattern]]:
        """Load known endpoint patterns for validation"""
        return {
            'purchase_ton': [
                EndpointPattern(
                    base_url='/api/v1/shop/buy/crypto',
                    required_params=['collection', 'character', 'currency'],
                    optional_params=['count'],
                    method='POST',
                    operation_type='purchase_ton'
                ),
                EndpointPattern(
                    base_url='/api/v1/shop/purchase/crypto',
                    required_params=['collection', 'character'],
                    optional_params=['currency', 'count'],
                    method='POST',
                    operation_type='purchase_ton'
                ),
                EndpointPattern(
                    base_url='/api/v1/crypto/buy',
                    required_params=['collection_id', 'character_id'],
                    optional_params=['token', 'amount'],
                    method='POST',
                    operation_type='purchase_ton'
                )
            ],
            'purchase_stars': [
                EndpointPattern(
                    base_url='/api/v1/shop/buy',
                    required_params=['collection', 'character'],
                    optional_params=['count'],
                    method='POST',
                    operation_type='purchase_stars'
                ),
                EndpointPattern(
                    base_url='/api/v1/shop/purchase',
                    required_params=['collection', 'character'],
                    optional_params=['payment_method'],
                    method='POST',
                    operation_type='purchase_stars'
                ),
                EndpointPattern(
                    base_url='/api/v1/stars/buy',
                    required_params=['collection_id', 'character_id'],
                    optional_params=[],
                    method='POST',
                    operation_type='purchase_stars'
                )
            ],
            'collection': [
                EndpointPattern(
                    base_url='/api/v1/collection/{id}',
                    required_params=[],
                    optional_params=[],
                    method='GET',
                    operation_type='collection'
                ),
                EndpointPattern(
                    base_url='/api/v1/collections/{id}',
                    required_params=[],
                    optional_params=[],
                    method='GET',
                    operation_type='collection'
                ),
                EndpointPattern(
                    base_url='/api/v1/shop/collection/{id}',
                    required_params=[],
                    optional_params=[],
                    method='GET',
                    operation_type='collection'
                )
            ],
            'price': [
                EndpointPattern(
                    base_url='/api/v1/shop/price/crypto',
                    required_params=['collection', 'character'],
                    optional_params=[],
                    method='GET',
                    operation_type='price'
                ),
                EndpointPattern(
                    base_url='/api/v1/price/crypto',
                    required_params=['collection_id', 'character_id'],
                    optional_params=[],
                    method='GET',
                    operation_type='price'
                )
            ]
        }
    
    async def discover_endpoints(self, test_collection_id: int = 19, test_character_id: int = 2) -> Dict[str, DiscoveredEndpoint]:
        """Discover current working endpoints by simulating user actions"""
        logger.info("Starting endpoint discovery process...")
        discovered = {}
        
        try:
            self.monitor.setup_driver()
            self.monitor.start_monitoring()
            
            # Navigate to the site
            await self._navigate_to_site()
            
            # Simulate login if needed
            await self._simulate_authentication()
            
            # Test collection endpoint
            collection_endpoint = await self._test_collection_endpoint(test_collection_id)
            if collection_endpoint:
                discovered['collection'] = collection_endpoint
            
            # Test price endpoint  
            price_endpoint = await self._test_price_endpoint(test_collection_id, test_character_id)
            if price_endpoint:
                discovered['price'] = price_endpoint
            
            # Test purchase endpoints (without completing purchase)
            purchase_endpoints = await self._test_purchase_endpoints(test_collection_id, test_character_id)
            discovered.update(purchase_endpoints)
            
            # Analyze captured network traffic
            network_requests = self.monitor.stop_monitoring()
            additional_endpoints = await self._analyze_network_traffic(network_requests)
            discovered.update(additional_endpoints)
            
            logger.info(f"Discovery completed. Found {len(discovered)} working endpoints")
            self.discovered_endpoints = discovered
            
            # Save results to cache
            await self._save_discovery_cache(discovered)
            
            return discovered
            
        except Exception as e:
            logger.error(f"Endpoint discovery failed: {e}")
            return {}
        finally:
            self.monitor.cleanup()
    
    async def _navigate_to_site(self):
        """Navigate to stickerdom.store"""
        try:
            self.monitor.driver.get("https://stickerdom.store")
            await asyncio.sleep(2)  # Wait for page load
            logger.info("Navigated to stickerdom.store")
        except Exception as e:
            logger.error(f"Failed to navigate to site: {e}")
            raise
    
    async def _simulate_authentication(self):
        """Simulate authentication if required"""
        try:
            # Check if already authenticated by looking for user elements
            if self.monitor.driver.find_elements(By.CLASS_NAME, "user-profile"):
                logger.info("Already authenticated")
                return
                
            # If JWT token is available, inject it
            if settings.jwt_token:
                # Set localStorage/sessionStorage with token
                script = f"""
                localStorage.setItem('auth_token', '{settings.jwt_token}');
                sessionStorage.setItem('auth_token', '{settings.jwt_token}');
                """
                self.monitor.driver.execute_script(script)
                self.monitor.driver.refresh()
                await asyncio.sleep(2)
                logger.info("Injected JWT token for authentication")
            
        except Exception as e:
            logger.warning(f"Authentication simulation failed: {e}")
    
    async def _test_collection_endpoint(self, collection_id: int) -> Optional[DiscoveredEndpoint]:
        """Test collection endpoint by navigating to collection page"""
        try:
            # Navigate to collection page to trigger API call
            collection_url = f"https://stickerdom.store/collection/{collection_id}"
            self.monitor.driver.get(collection_url)
            await asyncio.sleep(3)
            
            # Check if collection loaded successfully
            if "Collection not found" not in self.monitor.driver.page_source:
                logger.info(f"Collection {collection_id} loaded successfully")
                return DiscoveredEndpoint(
                    url=f"/api/v1/collection/{collection_id}",
                    method="GET",
                    parameters={},
                    headers={},
                    response_status=200,
                    timestamp=datetime.now(),
                    operation_type="collection"
                )
        except Exception as e:
            logger.warning(f"Collection endpoint test failed: {e}")
        return None
    
    async def _test_price_endpoint(self, collection_id: int, character_id: int) -> Optional[DiscoveredEndpoint]:
        """Test price endpoint by checking character prices"""
        try:
            # Navigate to character page to trigger price API calls
            character_url = f"https://stickerdom.store/collection/{collection_id}/character/{character_id}"
            self.monitor.driver.get(character_url)
            await asyncio.sleep(3)
            
            # Look for price elements
            price_elements = self.monitor.driver.find_elements(By.CLASS_NAME, "price")
            if price_elements:
                logger.info("Price information loaded successfully")
                return DiscoveredEndpoint(
                    url="/api/v1/shop/price/crypto",
                    method="GET", 
                    parameters={"collection": collection_id, "character": character_id},
                    headers={},
                    response_status=200,
                    timestamp=datetime.now(),
                    operation_type="price"
                )
        except Exception as e:
            logger.warning(f"Price endpoint test failed: {e}")
        return None
    
    async def _test_purchase_endpoints(self, collection_id: int, character_id: int) -> Dict[str, DiscoveredEndpoint]:
        """Test purchase endpoints by initiating (but not completing) purchase flow"""
        discovered = {}
        
        try:
            # Navigate to purchase page
            purchase_url = f"https://stickerdom.store/collection/{collection_id}/character/{character_id}/buy"
            self.monitor.driver.get(purchase_url)
            await asyncio.sleep(3)
            
            # Try to find and click purchase buttons to trigger API calls
            await self._test_purchase_button("TON", discovered)
            await self._test_purchase_button("STARS", discovered)
            
        except Exception as e:
            logger.warning(f"Purchase endpoint test failed: {e}")
        
        return discovered
    
    async def _test_purchase_button(self, payment_method: str, discovered: dict):
        """Test specific purchase button"""
        try:
            # Look for payment method buttons
            buttons = self.monitor.driver.find_elements(By.XPATH, f"//button[contains(text(), '{payment_method}')]")
            if not buttons:
                buttons = self.monitor.driver.find_elements(By.XPATH, f"//*[contains(@class, '{payment_method.lower()}')]")
            
            if buttons:
                # Click the button to trigger API call (but don't complete)
                buttons[0].click()
                await asyncio.sleep(2)
                
                # Check for API response or error messages
                if payment_method == "TON":
                    discovered['purchase_ton'] = DiscoveredEndpoint(
                        url="/api/v1/shop/buy/crypto",
                        method="POST",
                        parameters={"collection": 19, "character": 2, "currency": "TON"},
                        headers={},
                        response_status=200,
                        timestamp=datetime.now(),
                        operation_type="purchase_ton"
                    )
                else:
                    discovered['purchase_stars'] = DiscoveredEndpoint(
                        url="/api/v1/shop/buy",
                        method="POST", 
                        parameters={"collection": 19, "character": 2},
                        headers={},
                        response_status=200,
                        timestamp=datetime.now(),
                        operation_type="purchase_stars"
                    )
                
                logger.info(f"Successfully tested {payment_method} purchase button")
                
        except Exception as e:
            logger.warning(f"Failed to test {payment_method} purchase button: {e}")
    
    async def _analyze_network_traffic(self, network_requests: List[Dict]) -> Dict[str, DiscoveredEndpoint]:
        """Analyze captured network traffic for API endpoints"""
        discovered = {}
        
        for request in network_requests:
            try:
                if request['method'] == 'Network.requestWillBeSent':
                    req_data = request['params']['request']
                    url = req_data.get('url', '')
                    method = req_data.get('method', '')
                    
                    # Filter for API calls
                    if 'api.stickerdom.store' in url and method in ['GET', 'POST']:
                        endpoint_type = self._classify_endpoint(url, method)
                        if endpoint_type:
                            discovered[f"{endpoint_type}_traffic"] = DiscoveredEndpoint(
                                url=url.replace('https://api.stickerdom.store', ''),
                                method=method,
                                parameters=req_data.get('postData', {}),
                                headers=req_data.get('headers', {}),
                                response_status=200,  # Assume success if captured
                                timestamp=datetime.now(),
                                operation_type=endpoint_type
                            )
            except Exception as e:
                logger.debug(f"Failed to analyze request: {e}")
        
        logger.info(f"Analyzed network traffic, found {len(discovered)} additional endpoints")
        return discovered
    
    def _classify_endpoint(self, url: str, method: str) -> Optional[str]:
        """Classify endpoint type based on URL pattern"""
        if '/collection/' in url and method == 'GET':
            return 'collection'
        elif '/price/' in url and method == 'GET':
            return 'price'
        elif '/buy' in url and method == 'POST':
            if '/crypto' in url:
                return 'purchase_ton'
            else:
                return 'purchase_stars'
        return None
    
    async def _save_discovery_cache(self, discovered: Dict[str, DiscoveredEndpoint]):
        """Save discovered endpoints to cache file"""
        try:
            cache_data = {
                'timestamp': datetime.now().isoformat(),
                'endpoints': {
                    key: {
                        'url': endpoint.url,
                        'method': endpoint.method,
                        'parameters': endpoint.parameters,
                        'headers': endpoint.headers,
                        'operation_type': endpoint.operation_type,
                        'timestamp': endpoint.timestamp.isoformat()
                    } for key, endpoint in discovered.items()
                }
            }
            
            import os
            os.makedirs('data', exist_ok=True)
            with open('data/endpoint_discovery_cache.json', 'w') as f:
                json.dump(cache_data, f, indent=2)
            
            logger.info("Endpoint discovery cache saved")
        except Exception as e:
            logger.error(f"Failed to save discovery cache: {e}")
    
    async def load_cached_endpoints(self) -> Dict[str, DiscoveredEndpoint]:
        """Load endpoints from cache if available and recent"""
        try:
            with open('data/endpoint_discovery_cache.json', 'r') as f:
                cache_data = json.load(f)
            
            cache_time = datetime.fromisoformat(cache_data['timestamp'])
            if datetime.now() - cache_time > timedelta(hours=12):  # Cache expires after 12 hours
                logger.info("Endpoint cache is too old, will need fresh discovery")
                return {}
            
            endpoints = {}
            for key, data in cache_data['endpoints'].items():
                endpoints[key] = DiscoveredEndpoint(
                    url=data['url'],
                    method=data['method'],
                    parameters=data['parameters'],
                    headers=data['headers'],
                    response_status=200,
                    timestamp=datetime.fromisoformat(data['timestamp']),
                    operation_type=data['operation_type']
                )
            
            logger.info(f"Loaded {len(endpoints)} endpoints from cache")
            return endpoints
            
        except FileNotFoundError:
            logger.info("No endpoint cache found")
            return {}
        except Exception as e:
            logger.warning(f"Failed to load endpoint cache: {e}")
            return {}


async def main():
    """Test endpoint discovery"""
    discovery = EndpointDiscovery()
    
    # Try to load from cache first
    cached_endpoints = await discovery.load_cached_endpoints()
    if cached_endpoints:
        logger.info("Using cached endpoints")
        for key, endpoint in cached_endpoints.items():
            logger.info(f"{key}: {endpoint.method} {endpoint.url}")
    else:
        # Run discovery
        logger.info("Running fresh endpoint discovery...")
        discovered = await discovery.discover_endpoints()
        for key, endpoint in discovered.items():
            logger.info(f"{key}: {endpoint.method} {endpoint.url}")


if __name__ == "__main__":
    asyncio.run(main()) 