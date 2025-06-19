import asyncio
from typing import Optional, Dict, Any
from functools import lru_cache
import time
from curl_cffi import requests

from config import settings
from exceptions import APIError
from models import CollectionInfo, CharacterInfo
from utils.logger import logger

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
    
    async def _make_request_with_retry(
        self, 
        method: str, 
        url: str, 
        max_retries: Optional[int] = None,
        **kwargs
    ) -> requests.Response:
        """Make HTTP request with exponential backoff retry and CAPTCHA handling"""
        max_retries = max_retries or settings.max_retries_per_request
        last_exception = None
        
        for attempt in range(max_retries):
            try:
                response = getattr(self.session, method.lower())(url, **kwargs)
                
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
                            
                            # Add CAPTCHA solution to headers/params and retry
                            if 'headers' not in kwargs:
                                kwargs['headers'] = {}
                            kwargs['headers']['X-Captcha-Solution'] = solution.token
                            
                            # Retry request with solution
                            logger.info("🔄 Retrying request with CAPTCHA solution...")
                            continue
                            
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
        """Test API connection"""
        try:
            response = await self._make_request_with_retry(
                'GET',
                f"{self.api_base}/api/v1/shop/settings",
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
        currency: str = "TON"
    ) -> Optional[float]:
        """Get character price with caching"""
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
                params={
                    'collection': collection_id,
                    'character': character_id
                },
                timeout=settings.request_timeout
            )
            
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
    

    async def get_collection(self, collection_id: int) -> Optional[CollectionInfo]:
        """Get collection information"""
        try:
            response = await self._make_request_with_retry(
                'GET',
                f"{self.api_base}/api/v1/collection/{collection_id}",
                timeout=settings.request_timeout
            )
            
            if response.status_code == 404:
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
                    price=float(char.get('price', 0))
                )
                for char in characters_data
            ]
            
            return CollectionInfo(
                id=collection_data['id'],
                name=collection_data['title'],
                status=collection_data.get('status', 'inactive'),
                total_count=collection_data.get('total_count', 0),
                sold_count=collection_data.get('sold_count', 0),
                characters=characters
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
        """Initiate purchase with validation"""
        if count <= 0:
            raise APIError("Purchase count must be positive")
        if count > 10:  # Reasonable limit
            raise APIError("Purchase count too high")
            
        try:
            response = await self._make_request_with_retry(
                'POST',
                f"{self.api_base}/api/v1/shop/buy/crypto",
                params={
                    'collection': collection_id,
                    'character': character_id,
                    'currency': 'TON',
                    'count': count
                },
                timeout=settings.request_timeout * 2  # Purchase requests might take longer
            )
            
            if response.status_code != 200:
                error_text = response.text
                logger.error(f"Purchase initiation failed: {response.status_code} - {error_text}")
                raise APIError(f"Purchase initiation failed: HTTP {response.status_code}")
            
            data = response.json()
            if not data.get('ok'):
                error_msg = data.get('message', 'Unknown error')
                logger.error(f"Purchase initiation failed: {error_msg}")
                raise APIError(f"Purchase initiation failed: {error_msg}")
            
            purchase_data = data['data']
            
            # Validate response data
            required_fields = ['order_id', 'total_amount', 'wallet']
            for field in required_fields:
                if field not in purchase_data:
                    raise APIError(f"Invalid purchase response: missing {field}")
            
            logger.info(
                f"Purchase initiated: order_id={purchase_data['order_id']}, "
                f"amount={purchase_data['total_amount']/10**9:.9f} TON"
            )
            
            return purchase_data
            
        except APIError:
            raise
        except Exception as e:
            logger.error(f"Failed to initiate purchase: {e}")
            raise APIError(str(e))
        
    async def get_character_stars_invoice_url(
        self,
        collection_id: int,
        character_id: int,
        count: int = 5
    ) -> str:
        """Get Telegram Stars invoice URL for character purchase"""
        if count <= 0:
            raise APIError("Purchase count must be positive")
        if count > 10:  # Reasonable limit
            raise APIError("Purchase count too high")
            
        try:
            response = await self._make_request_with_retry(
                'POST',
                f"{self.api_base}/api/v1/shop/buy",
                params={
                    'collection': collection_id,
                    'character': character_id,
                    'count': count
                },
                timeout=settings.request_timeout * 2
            )
            
            if response.status_code != 200:
                error_text = response.text
                logger.error(f"Stars invoice creation failed: {response.status_code} - {error_text}")
                raise APIError(f"Stars invoice creation failed: HTTP {response.status_code}")
            
            data = response.json()
            if not data.get('ok'):
                error_msg = data.get('message', 'Unknown error')
                logger.error(f"Stars invoice creation failed: {error_msg}")
                raise APIError(f"Stars invoice creation failed: {error_msg}")
            
            invoice_url = data['data'].get('url')
            if not invoice_url:
                raise APIError("Invalid response: missing url")
            
            logger.info(f"Stars invoice created for collection {collection_id}, character {character_id}")
            return invoice_url
            
        except APIError:
            raise
        except Exception as e:
            logger.error(f"Failed to create Stars invoice: {e}")
            raise APIError(str(e))
        