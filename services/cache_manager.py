import asyncio
import time
from typing import Dict, Optional, Tuple
from decimal import Decimal
from dataclasses import dataclass

from .api_client import StickerdomAPI
from .ton_wallet import TONWalletManager
from models.wallet import WalletInfo
from utils.logger import logger
from config import settings


@dataclass
class CachedPrice:
    """Cached price information with timestamp"""
    collection_id: int
    character_id: int
    price_ton: float
    cached_at: float
    ttl: float = 30.0  # 30 seconds TTL by default
    
    @property
    def is_expired(self) -> bool:
        return time.time() - self.cached_at > self.ttl


@dataclass
class CachedBalance:
    """Cached wallet balance with timestamp"""
    wallet_info: WalletInfo
    cached_at: float
    ttl: float = 5.0  # 5 seconds TTL by default
    
    @property
    def is_expired(self) -> bool:
        return time.time() - self.cached_at > self.ttl


class StateCache:
    """
    Performance-optimized cache manager for wallet balance and character prices.
    Pre-loads critical data to avoid API calls during purchase execution.
    """
    
    def __init__(self, api_client: StickerdomAPI, wallet_manager: TONWalletManager):
        self.api = api_client
        self.wallet = wallet_manager
        
        # Cache storage
        self._price_cache: Dict[Tuple[int, int], CachedPrice] = {}
        self._balance_cache: Optional[CachedBalance] = None
        
        # Background update control
        self._update_task: Optional[asyncio.Task] = None
        self._running = False
        self._target_collections: set[Tuple[int, int]] = set()  # (collection_id, character_id)
        
        # Performance settings
        self.balance_update_interval = getattr(settings, 'cache_balance_interval', 2.0)  # 2 seconds
        self.price_update_interval = getattr(settings, 'cache_price_interval', 10.0)  # 10 seconds
    
    async def start_background_updates(self):
        """Start background cache updates"""
        if self._running:
            return
        
        self._running = True
        self._update_task = asyncio.create_task(self._background_update_loop())
        logger.info("Cache manager started with background updates")
    
    async def stop_background_updates(self):
        """Stop background cache updates"""
        if not self._running:
            return
        
        self._running = False
        if self._update_task:
            self._update_task.cancel()
            try:
                await self._update_task
            except asyncio.CancelledError:
                pass
        
        logger.info("Cache manager stopped")
    
    def add_target(self, collection_id: int, character_id: int):
        """Add collection/character pair to monitoring targets"""
        target = (collection_id, character_id)
        if target not in self._target_collections:
            self._target_collections.add(target)
            logger.info(f"Added cache target: collection {collection_id}, character {character_id}")
    
    def remove_target(self, collection_id: int, character_id: int):
        """Remove collection/character pair from monitoring"""
        target = (collection_id, character_id)
        self._target_collections.discard(target)
        
        # Clear price cache for removed target
        cache_key = (collection_id, character_id)
        if cache_key in self._price_cache:
            del self._price_cache[cache_key]
        
        logger.info(f"Removed cache target: collection {collection_id}, character {character_id}")
    
    async def get_cached_balance(self, force_refresh: bool = False) -> WalletInfo:
        """Get cached wallet balance, refresh if expired or forced"""
        if force_refresh or not self._balance_cache or self._balance_cache.is_expired:
            try:
                wallet_info = await self.wallet.get_wallet_info()
                self._balance_cache = CachedBalance(
                    wallet_info=wallet_info,
                    cached_at=time.time()
                )
                logger.debug(f"Balance cache refreshed: {wallet_info.balance_ton:.6f} TON")
            except Exception as e:
                logger.error(f"Failed to refresh balance cache: {e}")
                if self._balance_cache:
                    logger.warning("Using stale balance data")
                    return self._balance_cache.wallet_info
                raise
        
        return self._balance_cache.wallet_info
    
    async def get_cached_price(self, collection_id: int, character_id: int, force_refresh: bool = False) -> float:
        """Get cached character price, refresh if expired or forced"""
        cache_key = (collection_id, character_id)
        cached_price = self._price_cache.get(cache_key)
        
        if force_refresh or not cached_price or cached_price.is_expired:
            try:
                price_ton = await self.api.get_character_price(collection_id, character_id, "TON")
                if price_ton is None:
                    raise ValueError(f"Could not get price for character {character_id}")
                
                self._price_cache[cache_key] = CachedPrice(
                    collection_id=collection_id,
                    character_id=character_id,
                    price_ton=price_ton,
                    cached_at=time.time()
                )
                logger.debug(f"Price cache refreshed: {price_ton} TON for character {character_id}")
                return price_ton
                
            except Exception as e:
                logger.error(f"Failed to refresh price cache for character {character_id}: {e}")
                if cached_price:
                    logger.warning("Using stale price data")
                    return cached_price.price_ton
                raise
        
        return cached_price.price_ton
    
    async def preload_data(self, collection_id: int, character_id: int):
        """Preload cache data for specific collection/character"""
        logger.info(f"Preloading cache data for collection {collection_id}, character {character_id}")
        
        # Add to targets and start background updates if not running
        self.add_target(collection_id, character_id)
        if not self._running:
            await self.start_background_updates()
        
        # Force initial load
        try:
            await asyncio.gather(
                self.get_cached_balance(force_refresh=True),
                self.get_cached_price(collection_id, character_id, force_refresh=True),
                return_exceptions=True
            )
            logger.info("Cache preload completed successfully")
        except Exception as e:
            logger.error(f"Cache preload failed: {e}")
            raise
    
    async def _background_update_loop(self):
        """Background loop for cache updates"""
        last_balance_update = 0
        last_price_update = 0
        
        try:
            while self._running:
                current_time = time.time()
                
                # Update balance cache
                if current_time - last_balance_update >= self.balance_update_interval:
                    try:
                        await self.get_cached_balance(force_refresh=True)
                        last_balance_update = current_time
                    except Exception as e:
                        logger.error(f"Background balance update failed: {e}")
                
                # Update price cache for all targets
                if current_time - last_price_update >= self.price_update_interval and self._target_collections:
                    try:
                        tasks = [
                            self.get_cached_price(cid, chid, force_refresh=True)
                            for cid, chid in self._target_collections
                        ]
                        await asyncio.gather(*tasks, return_exceptions=True)
                        last_price_update = current_time
                    except Exception as e:
                        logger.error(f"Background price update failed: {e}")
                
                # Sleep with small interval for responsiveness
                await asyncio.sleep(0.5)
                
        except asyncio.CancelledError:
            logger.debug("Background cache update loop cancelled")
            raise
        except Exception as e:
            logger.error(f"Background cache update loop failed: {e}")
    
    def get_cache_stats(self) -> dict:
        """Get cache statistics for monitoring"""
        balance_age = 0
        if self._balance_cache:
            balance_age = time.time() - self._balance_cache.cached_at
        
        price_stats = {}
        for (cid, chid), cached_price in self._price_cache.items():
            price_age = time.time() - cached_price.cached_at
            price_stats[f"{cid}_{chid}"] = {
                "age_seconds": price_age,
                "price_ton": cached_price.price_ton,
                "expired": cached_price.is_expired
            }
        
        return {
            "balance_cache_age_seconds": balance_age,
            "balance_expired": self._balance_cache.is_expired if self._balance_cache else True,
            "price_cache": price_stats,
            "targets_count": len(self._target_collections),
            "cache_running": self._running
        } 