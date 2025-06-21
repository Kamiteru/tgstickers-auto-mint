import asyncio
from typing import Optional, Dict, Any
from functools import lru_cache
import time
import random
from curl_cffi import requests

from config import settings
from exceptions import APIError
from models import CollectionInfo, CharacterInfo
from utils.logger import logger
from .rate_limiter import RateLimiterService, RequestPriority
from .endpoint_manager import get_endpoint_manager

# Import CaptchaError for handling captcha-related exceptions
try:
    from exceptions import CaptchaError
except ImportError:
    # If CaptchaError is not in exceptions.py, define it locally
    class CaptchaError(Exception):
        pass

class StickerdomAPI:
    
    def __init__(self, captcha_manager=None):
        self.api_base = settings.api_base_url
        self.jwt_token = settings.jwt_token
        self.captcha_manager = captcha_manager
        self._price_cache: Dict[str, tuple[float, float]] = {}  # (price, timestamp)
        self._cache_ttl = 30  # Cache prices for 30 seconds
        
        # API capabilities (will be fetched during first connection)
        self._api_capabilities = None
        self._capabilities_checked = False
        
        # User-Agent rotation for IP ban bypass
        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/120.0',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        ]
        
        # Initialize rate limiter if enabled
        if settings.rate_limiter_enabled:
            # Detect test mode from environment or db path
            test_mode = ('test' in settings.rate_limiter_db_path.lower() or 
                        hasattr(settings, 'test_mode') and settings.test_mode)
            self.rate_limiter = RateLimiterService(settings.rate_limiter_db_path, test_mode=test_mode)
            logger.info("🚦 Advanced rate limiter enabled")
        else:
            self.rate_limiter = None
            logger.info("⚠️ Rate limiter disabled")
        
        # Initialize session with proxy support
        session_kwargs = {"impersonate": "chrome120"}
        
        # Setup proxy if enabled
        if settings.proxy_enabled and settings.proxy_url:
            session_kwargs["proxies"] = {
                'http': settings.proxy_url,
                'https': settings.proxy_url
            }
            logger.info(f"🔧 Proxy enabled: {settings.proxy_url}")
        
        self.session = requests.Session(**session_kwargs)
        
        # Set base headers
        base_headers = {
            'accept': 'application/json',
            'accept-language': 'ru,en;q=0.9',
            'authorization': f'Bearer {self.jwt_token}',
            'origin': 'https://stickerdom.store',
            'referer': 'https://stickerdom.store/',
            'user-agent': self._get_random_user_agent()
        }
        
        self.session.headers.update(base_headers)
        
        # Initialize adaptive endpoint system
        self.endpoint_manager = get_endpoint_manager(self)
        
        proxy_info = f" with proxy: {settings.proxy_url}" if settings.proxy_enabled else ""
        ua_info = " with User-Agent rotation" if settings.user_agent_rotation else ""
        
        if self.captcha_manager:
            logger.info(f"API client initialized with CAPTCHA support{proxy_info}{ua_info}")
        else:
            logger.info(f"API client initialized{proxy_info}{ua_info}")
    
    def _get_random_user_agent(self) -> str:
        """Get random User-Agent for IP ban bypass"""
        if settings.user_agent_rotation:
            return random.choice(self.user_agents)
        return self.user_agents[0]  # Default Chrome UA
    
    def _rotate_user_agent(self):
        """Rotate User-Agent header for next requests"""
        if settings.user_agent_rotation:
            new_ua = self._get_random_user_agent()
            self.session.headers.update({'user-agent': new_ua})
            logger.debug(f"🔄 Rotated User-Agent: {new_ua[:50]}...")
    
    async def _make_request_raw(
        self, 
        method: str, 
        url: str, 
        **kwargs
    ) -> requests.Response:
        """Make raw HTTP request without rate limiting"""
        # Rotate User-Agent for IP ban bypass
        self._rotate_user_agent()
        
        # Add conditional headers if rate limiter is available
        if self.rate_limiter:
            conditional_headers = self.rate_limiter.get_conditional_headers(url)
            if conditional_headers:
                if 'headers' not in kwargs:
                    kwargs['headers'] = {}
                kwargs['headers'].update(conditional_headers)
        
        response = getattr(self.session, method.lower())(url, **kwargs)
        
        # Update rate limiter state
        if self.rate_limiter:
            headers_dict = dict(response.headers)
            self.rate_limiter.update_from_headers(headers_dict, response.status_code)
            
            # Update cache headers
            if response.status_code == 200:
                self.rate_limiter.update_cache_headers(url, headers_dict)
            elif response.status_code == 304:
                # Not modified - return cached response indication
                logger.debug(f"📦 Using cached response for {url}")
        
        return response
    
    async def _make_request_with_retry(
        self, 
        method: str, 
        url: str, 
        priority: RequestPriority = RequestPriority.NORMAL,
        max_retries: Optional[int] = None,
        **kwargs
    ) -> requests.Response:
        """Make HTTP request with advanced rate limiting and retry logic"""
        max_retries = max_retries or settings.max_retries_per_request
        
        async def request_func():
            return await self._make_request_raw(method, url, **kwargs)
        
        # Use rate limiter if available
        if self.rate_limiter:
            return await self.rate_limiter.execute_with_rate_limit(
                request_func, 
                priority=priority,
                max_retries=max_retries
            )
        else:
            # Fallback to old retry logic
            return await self._legacy_retry_logic(request_func, max_retries)
    
    async def _legacy_retry_logic(
        self, 
        request_func: callable, 
        max_retries: int
    ) -> requests.Response:
        """Legacy retry logic for when rate limiter is disabled"""
        last_exception = None
        
        for attempt in range(max_retries):
            try:
                response = await request_func()
                
                if response.status_code == 429:  # Rate limit
                    retry_after = int(response.headers.get('Retry-After', 1))
                    logger.warning(f"Rate limited, waiting {retry_after}s")
                    await asyncio.sleep(retry_after)
                    continue
                
                # Check for CAPTCHA in response
                if self.captcha_manager and response.status_code in [200, 400, 403]:
                    try:
                        response_data = response.json()
                        captcha_challenge = self.captcha_manager.detect_captcha(response_data)
                        
                        if captcha_challenge:
                            logger.warning(f"🔒 CAPTCHA detected: {captcha_challenge.captcha_type}")
                            
                            # Solve CAPTCHA
                            solution = await self.captcha_manager.solve_captcha(captcha_challenge)
                            logger.info(f"✅ CAPTCHA solved via {solution.solver_method}")
                            
                            # Retry request with solution would require modifying request_func
                            logger.info("🔄 CAPTCHA handling in legacy mode - manual retry needed")
                            
                    except (ValueError, KeyError):
                        # Response is not JSON or doesn't contain captcha info
                        pass
                
                return response
                
            except Exception as e:
                last_exception = e
                if attempt < max_retries - 1:
                    wait_time = (2 ** attempt) + (attempt * 0.1)  # Exponential backoff
                    logger.warning(f"Request failed (attempt {attempt + 1}/{max_retries}), "
                                 f"retrying in {wait_time:.1f}s: {e}")
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"Request failed after {max_retries} attempts: {e}")
        
        raise APIError(f"Request failed after {max_retries} attempts: {last_exception}")

    async def test_connection(self) -> bool:
        """Test API connection and check capabilities"""
        try:
            # This will also check and cache capabilities
            capabilities = await self._check_api_capabilities()
            return capabilities is not None
        except Exception as e:
            logger.error(f"API connection test failed: {e}")
            return False
        
    async def _check_api_capabilities(self) -> Dict[str, Any]:
        """Check API capabilities and limitations"""
        if self._capabilities_checked and self._api_capabilities:
            return self._api_capabilities
        
        try:
            response = await self._make_request_raw(
                'GET',
                f"{self.api_base}/api/v1/shop/settings"
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get('ok'):
                    self._api_capabilities = data['data']
                    self._capabilities_checked = True
                    
                    # Log important limitations
                    if not self._api_capabilities.get('is_crypto_payment_enabled', True):
                        logger.warning("⚠️ Crypto payments are DISABLED on server")
                    
                    # Note: is_market_enabled is legacy - modern purchases use /shop/buy endpoints
                        
                    logger.info(f"📊 API capabilities: {self._api_capabilities}")
                    return self._api_capabilities
        
        except Exception as e:
            logger.warning(f"Failed to check API capabilities: {e}")
        
        # Default capabilities if check failed
        self._api_capabilities = {
            'is_crypto_payment_enabled': True,
            'is_transfer_enabled': True,
            'is_market_enabled': True,
            'crypto_orders_limit': 1
        }
        self._capabilities_checked = True
        return self._api_capabilities

    async def get_character_price(
        self, 
        collection_id: int, 
        character_id: int, 
        currency: str = "TON",
        priority: RequestPriority = RequestPriority.HIGH
    ) -> Optional[float]:
        """Get character price with caching and HIGH priority"""
        cache_key = f"{collection_id}:{character_id}:{currency}"
        
        # Check cache
        if cache_key in self._price_cache:
            price, timestamp = self._price_cache[cache_key]
            if time.time() - timestamp < self._cache_ttl:
                return price
        
        try:
            response = await self._make_request_with_retry(
                'GET',
                f"{self.api_base}/api/v1/shop/price/crypto",
                priority=priority,
                params={
                    'collection': collection_id,
                    'character': character_id
                },
                timeout=settings.request_timeout
            )
            
            # Handle 304 Not Modified
            if response.status_code == 304:
                # Use cached data if available
                if cache_key in self._price_cache:
                    price, _ = self._price_cache[cache_key]
                    # Update timestamp
                    self._price_cache[cache_key] = (price, time.time())
                    return price
                else:
                    logger.warning("Received 304 but no cached data available")
                    return None
            
            if response.status_code != 200:
                logger.error(f"Price API returned {response.status_code}: {response.text}")
                return None
            
            data = response.json()
            if not data.get('ok'):
                logger.error(f"Price API returned error: {data}")
                return None
            
            # Find price for specified currency
            for price_data in data['data']:
                if price_data.get('token_symbol') == currency:
                    price = float(price_data['price'])
                    # Cache the price
                    self._price_cache[cache_key] = (price, time.time())
                    return price
            
            logger.warning(f"Price for {currency} not found for {collection_id}/{character_id}")
            return None
            
        except Exception as e:
            logger.error(f"Failed to get price for {collection_id}/{character_id}: {e}")
            return None
    

    async def get_collection(
        self, 
        collection_id: int,
        priority: RequestPriority = RequestPriority.NORMAL
    ) -> Optional[CollectionInfo]:
        """Get collection information with configurable priority"""
        try:
            response = await self._make_request_with_retry(
                'GET',
                f"{self.api_base}/api/v1/collection/{collection_id}",
                priority=priority,
                timeout=settings.request_timeout
            )
            
            if response.status_code == 404:
                return None
            
            # Handle 304 Not Modified
            if response.status_code == 304:
                logger.debug(f"Collection {collection_id} not modified, using cached data")
                # This would require implementing collection caching
                return None
                
            if response.status_code != 200:
                logger.error(f"Collection API returned {response.status_code}: {response.text}")
                return None
            
            data = response.json()
            
            if not data.get('ok'):
                logger.error(f"Collection API returned error: {data}")
                return None
            
            collection_data = data['data']['collection']
            characters_data = data['data'].get('characters', [])
            
            characters = [
                CharacterInfo(
                    id=char['id'],
                    name=char['name'],
                    left=char.get('left', 0),
                    price=char.get('price', 0.0),
                    total=char.get('supply', char.get('total', 1)),  # Use 'supply' field if available
                    rarity=char.get('rarity', 'common')
                )
                for char in characters_data
            ]
            
            return CollectionInfo(
                id=collection_data['id'],
                name=collection_data.get('title', collection_data.get('name', f'Collection {collection_data["id"]}')),
                characters=characters,
                status=collection_data.get('status', 'active'),
                total_characters=len(characters),
                total_count=sum(char.total for char in characters),
                sold_count=sum(max(0, char.total - char.left) for char in characters)  # Prevent negative sold count
            )
            
        except Exception as e:
            logger.error(f"Failed to get collection {collection_id}: {e}")
            return None

    async def initiate_purchase(
        self,
        collection_id: int,
        character_id: int,
        count: int = 5
    ) -> Dict[str, Any]:
        """Initiate TON purchase using adaptive endpoint system"""
        try:
            # Check API capabilities first
            capabilities = await self._check_api_capabilities()
            
            # Check if crypto payments are enabled
            if not capabilities.get('is_crypto_payment_enabled', True):
                raise APIError("Crypto payments are disabled on server - TON purchases are not available")
            
            logger.info(f"🔍 Attempting TON purchase for collection {collection_id}, character {character_id}, count {count}")
            
            # Validate collection exists
            collection_info = await self.get_collection(collection_id)
            if not collection_info:
                raise APIError(f"Collection {collection_id} not found or inaccessible")
            
            logger.info(f"✅ Collection validated: {collection_info.name} (ID: {collection_info.id})")
            
            # Check if character exists in collection
            character_exists = any(char.id == character_id for char in collection_info.characters)
            if not character_exists:
                available_chars = [char.id for char in collection_info.characters]
                raise APIError(f"Character {character_id} not found in collection {collection_id}. Available: {available_chars}")
            
            logger.info(f"✅ Character {character_id} validated in collection")
            
            # Get best endpoint for TON purchase
            endpoint_info = await self.endpoint_manager.get_best_endpoint('purchase_ton')
            if not endpoint_info:
                raise APIError("No working TON purchase endpoints available")
            
            # Prepare parameters based on endpoint pattern
            params = endpoint_info.parameters.copy()
            params.update({
                'collection' if 'collection' in params else 'collection_id': collection_id,
                'character' if 'character' in params else 'character_id': character_id,
                'currency': 'TON',
                'count': count
            })
            
            logger.info(f"🚀 Using endpoint {endpoint_info.url} with params: {params}")
            
            start_time = time.time()
            try:
                response = await self._make_request_with_retry(
                    endpoint_info.method,
                    f"{self.api_base}{endpoint_info.url}",
                    priority=RequestPriority.CRITICAL,
                    params=params,
                    timeout=settings.request_timeout
                )
                
                response_time = time.time() - start_time
                
                logger.info(f"📥 Response status: {response.status_code}")
                
                if response.status_code != 200:
                    logger.error(f"📥 Raw response: {response.text}")
                    # Mark endpoint as failed and try fallback
                    self.endpoint_manager.mark_endpoint_failed('purchase_ton', endpoint_info.url, f"HTTP {response.status_code}")
                    
                    # Try fallback endpoint
                    fallback_endpoint = await self.endpoint_manager.get_best_endpoint('purchase_ton')
                    if fallback_endpoint and fallback_endpoint.url != endpoint_info.url:
                        logger.warning(f"Trying fallback endpoint: {fallback_endpoint.url}")
                        return await self.initiate_purchase(collection_id, character_id, count)
                    
                    raise APIError(f"Purchase API returned {response.status_code}: {response.text}")
                
                data = response.json()
                logger.info(f"📥 Response body: {data}")
                
                if not data.get('ok'):
                    error_code = data.get('errorCode', 'Unknown error')
                    logger.error(f"❌ API error code: {error_code}")
                    
                    # Mark endpoint as failed for certain errors
                    if error_code in ['endpoint_not_found', 'method_not_allowed', 'invalid_endpoint']:
                        self.endpoint_manager.mark_endpoint_failed('purchase_ton', endpoint_info.url, f"API error: {error_code}")
                    
                    raise APIError(f"Purchase API error: {error_code}")
                
                # Mark endpoint as successful
                self.endpoint_manager.mark_endpoint_success('purchase_ton', endpoint_info.url, response_time)
                
                purchase_data = data['data']
                
                # Parse the response from the endpoint
                result = {
                    'purchase_id': purchase_data.get('order_id'),
                    'wallet_address': purchase_data.get('wallet'),
                    'amount_ton': float(purchase_data.get('total_amount', 0)) / 1_000_000_000,
                    'currency': purchase_data.get('currency', 'TON'),
                    'expires_at': purchase_data.get('expires_at')
                }
                
                logger.info(f"✅ TON purchase initiated successfully - Order ID: {result['purchase_id']}")
                return result
                
            except Exception as e:
                response_time = time.time() - start_time
                logger.error(f"Request failed after {response_time:.2f}s: {e}")
                self.endpoint_manager.mark_endpoint_failed('purchase_ton', endpoint_info.url, str(e))
                raise
            
        except Exception as e:
            logger.error(f"Failed to initiate purchase for {collection_id}/{character_id}: {e}")
            raise

    async def get_character_stars_invoice_url(
        self,
        collection_id: int,
        character_id: int,
        count: int = 5
    ) -> str:
        """Get Stars payment invoice URL using adaptive endpoint system"""
        try:
            logger.info(f"🔍 Attempting Stars invoice for collection {collection_id}, character {character_id}, count {count}")
            
            # Validate collection exists
            collection_info = await self.get_collection(collection_id)
            if not collection_info:
                raise APIError(f"Collection {collection_id} not found or inaccessible")
            
            logger.info(f"✅ Collection validated: {collection_info.name} (ID: {collection_info.id})")
            
            # Check if character exists in collection
            character_exists = any(char.id == character_id for char in collection_info.characters)
            if not character_exists:
                available_chars = [char.id for char in collection_info.characters]
                raise APIError(f"Character {character_id} not found in collection {collection_id}. Available: {available_chars}")
            
            logger.info(f"✅ Character {character_id} validated in collection")
            
            # Get best endpoint for Stars purchase
            endpoint_info = await self.endpoint_manager.get_best_endpoint('purchase_stars')
            if not endpoint_info:
                raise APIError("No working STARS purchase endpoints available")
            
            # Prepare parameters based on endpoint pattern
            params = endpoint_info.parameters.copy()
            params.update({
                'collection' if 'collection' in params else 'collection_id': collection_id,
                'character' if 'character' in params else 'character_id': character_id
            })
            
            logger.info(f"🚀 Using endpoint {endpoint_info.url} with params: {params}")
            
            start_time = time.time()
            try:
                response = await self._make_request_with_retry(
                    endpoint_info.method,
                    f"{self.api_base}{endpoint_info.url}",
                    priority=RequestPriority.CRITICAL,
                    params=params,
                    timeout=settings.request_timeout
                )
                
                response_time = time.time() - start_time
                
                logger.info(f"📥 STARS response status: {response.status_code}")
                
                if response.status_code != 200:
                    logger.error(f"📥 Raw response: {response.text}")
                    # Mark endpoint as failed and try fallback
                    self.endpoint_manager.mark_endpoint_failed('purchase_stars', endpoint_info.url, f"HTTP {response.status_code}")
                    
                    # Try fallback endpoint
                    fallback_endpoint = await self.endpoint_manager.get_best_endpoint('purchase_stars')
                    if fallback_endpoint and fallback_endpoint.url != endpoint_info.url:
                        logger.warning(f"Trying fallback endpoint: {fallback_endpoint.url}")
                        return await self.get_character_stars_invoice_url(collection_id, character_id, count)
                    
                    raise APIError(f"STARS purchase API returned {response.status_code}: {response.text}")
                
                data = response.json()
                logger.info(f"📥 STARS response body: {data}")
                
                if not data.get('ok'):
                    error_code = data.get('errorCode', 'Unknown error')
                    logger.error(f"❌ API error code: {error_code}")
                    
                    # Mark endpoint as failed for certain errors
                    if error_code in ['endpoint_not_found', 'method_not_allowed', 'invalid_endpoint']:
                        self.endpoint_manager.mark_endpoint_failed('purchase_stars', endpoint_info.url, f"API error: {error_code}")
                    
                    raise APIError(f"STARS purchase API error: {error_code}")
                
                # Mark endpoint as successful
                self.endpoint_manager.mark_endpoint_success('purchase_stars', endpoint_info.url, response_time)
                
                purchase_data = data['data']
                
                # Extract invoice URL from response
                invoice_url = purchase_data.get('invoice_url')
                if not invoice_url:
                    # Try other possible field names
                    invoice_url = purchase_data.get('payment_url') or purchase_data.get('url')
                
                if not invoice_url:
                    logger.error(f"❌ No invoice URL in response: {purchase_data}")
                    raise APIError("STARS invoice URL not found in API response")
                
                logger.info(f"✅ Stars invoice URL obtained: {invoice_url}")
                return invoice_url
                
            except Exception as e:
                response_time = time.time() - start_time
                logger.error(f"Request failed after {response_time:.2f}s: {e}")
                self.endpoint_manager.mark_endpoint_failed('purchase_stars', endpoint_info.url, str(e))
                raise
            
        except Exception as e:
            logger.error(f"Failed to get Stars invoice for {collection_id}/{character_id}: {e}")
            raise

    def get_rate_limiter_metrics(self) -> Optional[Dict[str, Any]]:
        """Get rate limiter metrics for monitoring"""
        if self.rate_limiter:
            return self.rate_limiter.get_metrics()
        return None

    async def cleanup(self):
        """Clean up resources"""
        if self.rate_limiter:
            # Clean up any pending requests
            async with self.rate_limiter.rate_limited_session():
                pass
        
        # Save endpoint manager state
        if self.endpoint_manager:
            self.endpoint_manager.save_state()
        
        # Close session
        if hasattr(self.session, 'close'):
            self.session.close()
        