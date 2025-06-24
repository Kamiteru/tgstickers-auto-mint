#!/usr/bin/env python3
"""
Threaded Purchase Manager - система многопоточных покупок с разными прокси
Позволяет спамить покупки одной коллекции с разных IP адресов
"""

import asyncio
import time
from typing import List, Optional, Dict, Any, Callable
from dataclasses import dataclass, field
import random

from utils.logger import logger
from .api_client import StickerdomAPI
from .proxy_manager import proxy_manager
from .jwt_manager import get_token
from .purchase_orchestrator import PurchaseOrchestrator
from .ton_wallet import TONWalletManager
from .telegram_stars import TelegramStarsPayment
from .captcha_solver import CaptchaManager
from config import settings


@dataclass
class PurchaseTask:
    """Task for purchase worker"""
    collection_id: int
    character_id: int
    task_id: str = field(default_factory=lambda: f"task_{int(time.time() * 1000)}")
    priority: int = 0
    created_at: float = field(default_factory=time.time)


@dataclass
class WorkerResult:
    """Result from purchase worker"""
    worker_id: int
    task: PurchaseTask
    success: bool
    stickers_bought: int = 0
    error: Optional[str] = None
    proxy_used: Optional[str] = None
    execution_time: float = 0.0


class PurchaseWorker:
    """Individual purchase worker with dedicated proxy and API client"""
    
    def __init__(self, worker_id: int, proxy_config: Optional[Dict] = None):
        self.worker_id = worker_id
        self.proxy_config = proxy_config
        self.proxy_url = proxy_config['url'] if proxy_config else 'direct'
        
        # Create dedicated API client for this worker
        self.captcha_manager = CaptchaManager() if settings.captcha_enabled else None
        self.api_client = StickerdomAPI(self.captcha_manager)
        
        # Create dedicated orchestrator
        wallet = TONWalletManager() if 'TON' in settings.payment_methods else None
        stars_payment = TelegramStarsPayment() if 'STARS' in settings.payment_methods else None
        self.orchestrator = PurchaseOrchestrator(self.api_client, wallet, stars_payment)
        
        self.active = False
        logger.info(f"Worker {worker_id} initialized with proxy: {self.proxy_url}")
    
    async def execute_task(self, task: PurchaseTask) -> WorkerResult:
        """Execute purchase task"""
        start_time = time.time()
        self.active = True
        
        try:
            logger.debug(f"Worker {self.worker_id} executing task {task.task_id}")
            
            # Execute purchase
            results = await self.orchestrator.execute_multiple_purchases(
                task.collection_id, 
                task.character_id
            )
            
            successful_count = sum(1 for r in results if r.is_successful)
            total_stickers = successful_count  # Each purchase is 1 pack, stickers count varies
            
            execution_time = time.time() - start_time
            
            if successful_count > 0:
                logger.info(
                    f"Worker {self.worker_id} SUCCESS: {successful_count} purchases "
                    f"({total_stickers} packs) in {execution_time:.2f}s"
                )
                return WorkerResult(
                    worker_id=self.worker_id,
                    task=task,
                    success=True,
                    stickers_bought=total_stickers,
                    proxy_used=self.proxy_url,
                    execution_time=execution_time
                )
            else:
                error_msg = "All purchase attempts failed"
                if results:
                    last_error = next((r.error_message for r in reversed(results) if r.error_message), None)
                    if last_error:
                        error_msg = last_error
                
                logger.warning(f"Worker {self.worker_id} FAILED: {error_msg}")
                return WorkerResult(
                    worker_id=self.worker_id,
                    task=task,
                    success=False,
                    error=error_msg,
                    proxy_used=self.proxy_url,
                    execution_time=execution_time
                )
                
        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(f"Worker {self.worker_id} ERROR: {e}")
            return WorkerResult(
                worker_id=self.worker_id,
                task=task,
                success=False,
                error=str(e),
                proxy_used=self.proxy_url,
                execution_time=execution_time
            )
        finally:
            self.active = False
    
    async def close(self):
        """Close worker resources"""
        if hasattr(self.orchestrator, 'wallet') and self.orchestrator.wallet:
            await self.orchestrator.wallet.close()
        if hasattr(self.orchestrator, 'stars_payment') and self.orchestrator.stars_payment:
            await self.orchestrator.stars_payment.close_session()


class ThreadedPurchaseManager:
    """Manage multiple purchase workers with different proxies"""
    
    def __init__(self, max_workers: Optional[int] = None):
        proxy_count = proxy_manager.get_proxy_count() if proxy_manager.is_enabled() else 1
        self.max_workers = max_workers or min(proxy_count, 10)
        if self.max_workers == 0:
            self.max_workers = 1  # Fallback for no proxy case
            
        self.workers: List[PurchaseWorker] = []
        self.task_queue: asyncio.Queue = asyncio.Queue()
        self.result_callback: Optional[Callable] = None
        self.running = False
        self.worker_tasks: List[asyncio.Task] = []
        
        logger.info(f"ThreadedPurchaseManager initialized with {self.max_workers} workers")
    
    async def initialize(self):
        """Initialize workers with different proxies"""
        logger.info("Initializing purchase workers...")
        
        # Get available proxies
        available_proxies = []
        if proxy_manager.is_enabled():
            for _ in range(self.max_workers):
                proxy = proxy_manager.get_random_proxy()
                if proxy:
                    available_proxies.append(proxy)
        
        # Create workers
        for i in range(self.max_workers):
            proxy_config = available_proxies[i] if i < len(available_proxies) else None
            worker = PurchaseWorker(i + 1, proxy_config)
            self.workers.append(worker)
        
        logger.info(f"Created {len(self.workers)} workers")
        
        # Log proxy distribution
        proxy_distribution = {}
        for worker in self.workers:
            proxy_key = worker.proxy_url
            proxy_distribution[proxy_key] = proxy_distribution.get(proxy_key, 0) + 1
        
        for proxy, count in proxy_distribution.items():
            logger.info(f"Proxy {proxy}: {count} workers")
    
    async def start(self):
        """Start worker tasks"""
        if self.running:
            logger.warning("ThreadedPurchaseManager already running")
            return
        
        self.running = True
        logger.info("Starting worker tasks...")
        
        # Start worker tasks
        for worker in self.workers:
            task = asyncio.create_task(self._worker_loop(worker))
            self.worker_tasks.append(task)
        
        logger.info(f"Started {len(self.worker_tasks)} worker tasks")
    
    async def _worker_loop(self, worker: PurchaseWorker):
        """Worker loop to process tasks from queue"""
        logger.debug(f"Worker {worker.worker_id} started processing loop")
        
        while self.running:
            try:
                # Wait for task with timeout
                task = await asyncio.wait_for(self.task_queue.get(), timeout=1.0)
                
                # Execute task
                result = await worker.execute_task(task)
                
                # Report result
                if self.result_callback:
                    await self.result_callback(result)
                
                # Mark task done
                self.task_queue.task_done()
                
            except asyncio.TimeoutError:
                # No task available, continue loop
                continue
            except Exception as e:
                logger.error(f"Worker {worker.worker_id} error: {e}")
                await asyncio.sleep(1)
        
        logger.debug(f"Worker {worker.worker_id} stopped")
    
    async def add_purchase_task(self, collection_id: int, character_id: int, priority: int = 0):
        """Add purchase task to queue"""
        task = PurchaseTask(
            collection_id=collection_id,
            character_id=character_id,
            priority=priority
        )
        
        await self.task_queue.put(task)
        logger.debug(f"Added task {task.task_id} to queue")
    
    async def spam_collection(
        self, 
        collection_id: int, 
        character_id: int, 
        total_attempts: int = 50,
        delay_between_attempts: float = 0.1
    ):
        """Spam purchase attempts on a collection with multiple workers"""
        logger.info(
            f"Starting spam mode: {total_attempts} attempts on collection {collection_id}, "
            f"character {character_id} with {len(self.workers)} workers"
        )
        
        # Add all tasks to queue
        for i in range(total_attempts):
            await self.add_purchase_task(collection_id, character_id, priority=i)
            
            # Small delay to prevent overwhelming
            if delay_between_attempts > 0:
                await asyncio.sleep(delay_between_attempts)
        
        logger.info(f"Added {total_attempts} purchase tasks to queue")
    
    def set_result_callback(self, callback: Callable[[WorkerResult], None]):
        """Set callback for handling results"""
        self.result_callback = callback
    
    def get_active_workers(self) -> int:
        """Get number of currently active workers"""
        return sum(1 for worker in self.workers if worker.active)
    
    def get_queue_size(self) -> int:
        """Get current queue size"""
        return self.task_queue.qsize()
    
    def get_status(self) -> Dict[str, Any]:
        """Get manager status"""
        return {
            "running": self.running,
            "total_workers": len(self.workers),
            "active_workers": self.get_active_workers(),
            "queue_size": self.get_queue_size(),
            "proxy_enabled": proxy_manager.is_enabled(),
            "proxy_count": proxy_manager.get_proxy_count()
        }
    
    async def stop(self):
        """Stop all workers"""
        if not self.running:
            return
        
        logger.info("Stopping ThreadedPurchaseManager...")
        self.running = False
        
        # Cancel worker tasks
        for task in self.worker_tasks:
            task.cancel()
        
        # Wait for tasks to complete
        if self.worker_tasks:
            await asyncio.gather(*self.worker_tasks, return_exceptions=True)
        
        # Close workers
        for worker in self.workers:
            await worker.close()
        
        logger.info("ThreadedPurchaseManager stopped")
    
    async def wait_for_completion(self, timeout: Optional[float] = None):
        """Wait for all tasks in queue to complete"""
        try:
            await asyncio.wait_for(self.task_queue.join(), timeout=timeout)
            logger.info("All purchase tasks completed")
        except asyncio.TimeoutError:
            logger.warning(f"Timeout waiting for task completion after {timeout}s")


# Global threaded purchase manager
threaded_purchase_manager = ThreadedPurchaseManager() 