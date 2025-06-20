import asyncio
from typing import Callable, Set, Dict

from services.api_client import StickerdomAPI
from models import CollectionInfo
from config import settings
from utils.logger import logger
from utils.notifications import notifier


class CollectionWatcher:
    
    def __init__(self, api_client: StickerdomAPI):
        self.api = api_client
        self._watched_collections: Set[int] = set()
        self._tasks: Set[asyncio.Task] = set()
        self._collection_not_found_count: Dict[int, int] = {}
    

    async def watch_collection(
        self,
        collection_id: int,
        character_id: int,
        on_available: Callable[[CollectionInfo, int], None]
    ):
        if collection_id in self._watched_collections:
            logger.warning(f"Collection {collection_id} is already being watched")
            return
        
        self._watched_collections.add(collection_id)
        self._collection_not_found_count[collection_id] = 0
        
        task = asyncio.create_task(
            self._monitor_collection(collection_id, character_id, on_available)
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        
        logger.info(f"Started watching collection {collection_id}, character {character_id}")
    

    async def _monitor_collection(
        self,
        collection_id: int,
        character_id: int,
        callback: Callable[[CollectionInfo, int], None]
    ):
        last_stock = 0
        collection_found = False
        
        # Import RequestPriority for background monitoring
        from services.rate_limiter import RequestPriority
        
        while collection_id in self._watched_collections:
            try:
                collection = await self.api.get_collection(collection_id, priority=RequestPriority.LOW)
                
                if collection is None:
                    self._collection_not_found_count[collection_id] += 1
                    
                    if not collection_found:
                        if self._collection_not_found_count[collection_id] % 5 == 1:
                            logger.info(
                                f"Collection {collection_id} not found yet. "
                                f"Waiting for it to appear... (attempt #{self._collection_not_found_count[collection_id]})"
                            )
                    
                    await asyncio.sleep(settings.collection_not_found_retry)
                    continue
                
                if not collection_found:
                    collection_found = True
                    logger.info(f"Collection {collection_id} '{collection.name}' found! Starting monitoring...")
                    
                    # Send notification about collection being found
                    character = next((c for c in collection.characters if c.id == character_id), None)
                    if character:
                        # character.price is already in stars (Telegram's internal currency)
                        await notifier.notify_collection_found(
                            collection.name,
                            character.name,
                            character.left,
                            price_stars=int(character.price),
                            price_ton=None
                        )
                
                if collection.is_active:
                    character = next((c for c in collection.characters if c.id == character_id), None)
                    
                    if character:
                        if character.is_available:
                            if character.left > last_stock or last_stock == 0:
                                # character.price is already in stars (Telegram's internal currency)
                                logger.info(
                                    f"Character {character.name} is available! "
                                    f"Stock: {character.left}, Price: {int(character.price)} stars per sticker"
                                )
                                await callback(collection, character_id)
                            last_stock = character.left
                        else:
                            if last_stock > 0:
                                logger.info(f"Character {character.name} sold out")
                            last_stock = 0
                    else:
                        logger.warning(f"Character {character_id} not found in collection")
                else:
                    logger.debug(f"Collection {collection_id} not active yet (status: {collection.status})")
                
                await asyncio.sleep(settings.collection_check_interval)
                
            except Exception as e:
                logger.error(f"Error monitoring collection {collection_id}: {e}")
                await asyncio.sleep(settings.collection_check_interval)
    

    def stop_watching(self, collection_id: int):
        if collection_id in self._watched_collections:
            self._watched_collections.remove(collection_id)
            self._collection_not_found_count.pop(collection_id, None)
            logger.info(f"Stopped watching collection {collection_id}")
    

    async def stop_all(self):
        self._watched_collections.clear()
        self._collection_not_found_count.clear()
        
        for task in self._tasks:
            task.cancel()
        
        await asyncio.gather(*self._tasks, return_exceptions=True)
        logger.info("All monitoring tasks stopped")
