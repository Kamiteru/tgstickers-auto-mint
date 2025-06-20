import asyncio
from typing import Optional, Dict, Any
from functools import lru_cache
import time
from curl_cffi import requests

from config import settings
from exceptions import APIError
from models import CollectionInfo, CharacterInfo
from utils.logger import logger
from .rate_limiter import RateLimiterService, RequestPriority

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
        
        self.session = requests.Session(impersonate="chrome120")
        self.session.headers.update({
            'accept': 'application/json',
            'accept-language': 'ru,en;q=0.9',
            'authorization': f'Bearer {self.jwt_token}',
            'origin': 'https://stickerdom.store',
            'referer': 'https://stickerdom.store/',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        
        if self.captcha_manager:
            logger.info("API client initialized with CAPTCHA support")
        else:
            logger.info("API client initialized")
    
    async def _make_request_raw(
        self, 
        method: str, 
        url: str, 
        **kwargs
    ) -> requests.Response:
        """Make raw HTTP request without rate limiting"""
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
        """Test API connection with LOW priority"""
        try:
            response = await self._make_request_with_retry(
                'GET',
                f"{self.api_base}/api/v1/shop/settings",
                priority=RequestPriority.LOW,
                timeout=10,
                max_retries=2
            )
            return response.status_code == 200
        except Exception as e:
            logger.error(f"API connection test failed: {e}")
            return False
        

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
                    total=char.get('total', 1),
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
                sold_count=sum(char.total - char.left for char in characters)
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
        """Initiate purchase with CRITICAL priority"""
        try:
            response = await self._make_request_with_retry(
                'POST',
                f"{self.api_base}/api/v1/shop/purchase/crypto",
                priority=RequestPriority.CRITICAL,  # Highest priority for purchases
                json={
                    'collection': collection_id,
                    'character': character_id,
                    'count': count,
                    'crypto': 'TON'
                },
                timeout=settings.request_timeout
            )
            
            if response.status_code != 200:
                raise APIError(f"Purchase API returned {response.status_code}: {response.text}")
            
            data = response.json()
            if not data.get('ok'):
                raise APIError(f"Purchase API returned error: {data}")
            
            purchase_data = data['data']
            
            return {
                'purchase_id': purchase_data['purchase_id'],
                'wallet_address': purchase_data['wallet_address'],
                'amount_ton': float(purchase_data['amount']),
                'memo': purchase_data.get('memo', ''),
                'expires_at': purchase_data.get('expires_at')
            }
            
        except Exception as e:
            logger.error(f"Failed to initiate purchase for {collection_id}/{character_id}: {e}")
            raise

    async def get_character_stars_invoice_url(
        self,
        collection_id: int,
        character_id: int,
        count: int = 5
    ) -> str:
        """Get Stars payment invoice URL with CRITICAL priority"""
        try:
            response = await self._make_request_with_retry(
                'POST',
                f"{self.api_base}/api/v1/shop/purchase/stars",
                priority=RequestPriority.CRITICAL,  # Highest priority for purchases
                json={
                    'collection': collection_id,
                    'character': character_id,
                    'count': count
                },
                timeout=settings.request_timeout
            )
            
            if response.status_code != 200:
                raise APIError(f"Stars invoice API returned {response.status_code}: {response.text}")
            
            data = response.json()
            if not data.get('ok'):
                raise APIError(f"Stars invoice API returned error: {data}")
            
            return data['data']['invoice_url']
            
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
        
        # Close session
        if hasattr(self.session, 'close'):
            self.session.close()
        