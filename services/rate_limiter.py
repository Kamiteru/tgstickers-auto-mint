import asyncio
import sqlite3
import time
import random
import json
from typing import Optional, Dict, Any, Callable, Awaitable
from dataclasses import dataclass, asdict
from pathlib import Path
from enum import Enum
from contextlib import asynccontextmanager

from utils.logger import logger


class RequestPriority(Enum):
    """Request priority levels"""
    CRITICAL = 1    # Purchase requests
    HIGH = 2       # Price checks for active monitoring
    NORMAL = 3     # Collection info
    LOW = 4        # Background updates


@dataclass
class RateLimitState:
    """Rate limit state from API headers"""
    remaining: int = 1000
    reset_timestamp: float = 0
    retry_after: Optional[int] = None
    last_updated: float = 0
    
    @property
    def seconds_until_reset(self) -> float:
        """Seconds until rate limit resets"""
        return max(0, self.reset_timestamp - time.time())
    
    @property
    def is_exhausted(self) -> bool:
        """Check if rate limit is exhausted"""
        return self.remaining <= 0 and self.seconds_until_reset > 0


@dataclass
class RequestItem:
    """Queued request item"""
    priority: RequestPriority
    func: Callable[[], Awaitable[Any]]
    future: asyncio.Future
    created_at: float
    retries: int = 0
    max_retries: int = 5
    
    def __lt__(self, other):
        """Enable comparison for priority queue"""
        if not isinstance(other, RequestItem):
            return NotImplemented
        # Lower priority value = higher priority (critical=1, low=4)
        if self.priority.value != other.priority.value:
            return self.priority.value < other.priority.value
        # If same priority, older requests first
        return self.created_at < other.created_at


class RateLimiterService:
    """Advanced rate limiter with persistent state and request queue"""
    
    def __init__(self, db_path: str = "data/rate_limiter.db", test_mode: bool = False):
        self.db_path = Path(db_path)
        # Create data directory if it doesn't exist
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.state = RateLimitState()
        self.request_queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self.is_processing = False
        self.circuit_breaker_until: float = 0
        self.consecutive_failures = 0
        self.etag_cache: Dict[str, str] = {}
        self.last_modified_cache: Dict[str, str] = {}
        
        # Test mode settings
        self.test_mode = test_mode
        self.max_wait_time = 10 if test_mode else 300  # Max 10s in test, 5min in production
        self.circuit_breaker_duration = 5 if test_mode else 300  # 5s in test, 5min in production
        
        # Initialize database
        self._init_db()
        self._load_state()
        
        logger.info(f"🚦 Rate limiter service initialized {'(TEST MODE)' if test_mode else ''}")
    
    def _init_db(self):
        """Initialize SQLite database for persistent state"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS rate_limit_state (
                    id INTEGER PRIMARY KEY,
                    remaining INTEGER,
                    reset_timestamp REAL,
                    retry_after INTEGER,
                    last_updated REAL,
                    etag_cache TEXT,
                    last_modified_cache TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS request_metrics (
                    timestamp REAL,
                    endpoint TEXT,
                    status_code INTEGER,
                    response_time REAL,
                    rate_limited BOOLEAN
                )
            """)
    
    def _load_state(self):
        """Load rate limit state from database"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                row = conn.execute("SELECT * FROM rate_limit_state ORDER BY id DESC LIMIT 1").fetchone()
                if row:
                    self.state = RateLimitState(
                        remaining=row[1],
                        reset_timestamp=row[2],
                        retry_after=row[3],
                        last_updated=row[4]
                    )
                    if row[5]:
                        self.etag_cache = json.loads(row[5])
                    if row[6]:
                        self.last_modified_cache = json.loads(row[6])
                    
                    logger.info(f"📊 Loaded rate limit state: {self.state.remaining} remaining")
        except Exception as e:
            logger.warning(f"Failed to load rate limit state: {e}")
    
    def _save_state(self):
        """Save current state to database"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT INTO rate_limit_state 
                    (remaining, reset_timestamp, retry_after, last_updated, etag_cache, last_modified_cache)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    self.state.remaining,
                    self.state.reset_timestamp,
                    self.state.retry_after,
                    self.state.last_updated,
                    json.dumps(self.etag_cache),
                    json.dumps(self.last_modified_cache)
                ))
        except Exception as e:
            logger.warning(f"Failed to save rate limit state: {e}")
    
    def update_from_headers(self, headers: Dict[str, str], status_code: int):
        """Update rate limit state from response headers"""
        try:
            # Parse standard rate limit headers
            if 'x-ratelimit-remaining' in headers:
                self.state.remaining = int(headers['x-ratelimit-remaining'])
            
            if 'x-ratelimit-reset' in headers:
                self.state.reset_timestamp = float(headers['x-ratelimit-reset'])
            
            if 'retry-after' in headers:
                self.state.retry_after = int(headers['retry-after'])
            
            self.state.last_updated = time.time()
            
            # Handle 429 specifically
            if status_code == 429:
                self.consecutive_failures += 1
                if self.consecutive_failures >= 3:
                    # Activate circuit breaker 
                    self.circuit_breaker_until = time.time() + self.circuit_breaker_duration
                    duration_text = f"{self.circuit_breaker_duration}s"
                    logger.warning(f"🚨 Circuit breaker activated for {duration_text} due to repeated rate limiting")
            else:
                self.consecutive_failures = 0
            
            self._save_state()
            
            logger.debug(f"🔄 Rate limit updated: {self.state.remaining} remaining, "
                        f"resets in {self.state.seconds_until_reset:.1f}s")
                        
        except (ValueError, KeyError) as e:
            logger.warning(f"Failed to parse rate limit headers: {e}")
    
    def get_conditional_headers(self, url: str) -> Dict[str, str]:
        """Get conditional request headers for caching"""
        headers = {}
        
        if url in self.etag_cache:
            headers['If-None-Match'] = self.etag_cache[url]
        
        if url in self.last_modified_cache:
            headers['If-Modified-Since'] = self.last_modified_cache[url]
        
        return headers
    
    def update_cache_headers(self, url: str, headers: Dict[str, str]):
        """Update cache headers from response"""
        if 'etag' in headers:
            self.etag_cache[url] = headers['etag']
        
        if 'last-modified' in headers:
            self.last_modified_cache[url] = headers['last-modified']
    
    def calculate_backoff_delay(self, attempt: int, base_delay: float = 1.0) -> float:
        """Calculate exponential backoff with jitter and smart capping"""
        if self.state.retry_after:
            # Cap retry_after to max_wait_time to avoid extreme delays
            capped_retry = min(self.state.retry_after, self.max_wait_time)
            if capped_retry < self.state.retry_after:
                logger.warning(f"⚠️ Capping retry-after from {self.state.retry_after}s to {capped_retry}s")
            return capped_retry
        
        # Exponential backoff: 2^attempt * base_delay + jitter
        delay = min((2 ** attempt) * base_delay, self.max_wait_time)
        jitter = delay * 0.1 * random.random()  # Add 0-10% jitter
        
        return delay + jitter
    
    async def should_wait_before_request(self) -> bool:
        """Check if we should wait before making a request"""
        now = time.time()
        
        # Check circuit breaker
        if now < self.circuit_breaker_until:
            wait_time = self.circuit_breaker_until - now
            logger.warning(f"🚨 Circuit breaker active, waiting {wait_time:.1f}s")
            await asyncio.sleep(wait_time)
            return True
        
        # Check if rate limit is exhausted
        if self.state.is_exhausted:
            wait_time = min(self.state.seconds_until_reset + 1, self.max_wait_time)  # Cap wait time
            if wait_time < self.state.seconds_until_reset + 1:
                logger.warning(f"⚠️ Capping rate limit wait from {self.state.seconds_until_reset + 1:.1f}s to {wait_time:.1f}s")
            logger.warning(f"⏳ Rate limit exhausted, waiting {wait_time:.1f}s")
            await asyncio.sleep(wait_time)
            return True
        
        # Proactive slowdown when approaching limit
        if self.state.remaining <= 10:
            delay = min(60, self.max_wait_time)  # Cap proactive delay too
            logger.warning(f"⚠️ Rate limit low ({self.state.remaining}), waiting {delay}s")
            await asyncio.sleep(delay)
            return True
        
        return False
    
    async def execute_with_rate_limit(
        self, 
        func: Callable[[], Awaitable[Any]], 
        priority: RequestPriority = RequestPriority.NORMAL,
        max_retries: int = 5
    ) -> Any:
        """Execute function with rate limiting and queuing"""
        
        # Create request item
        future = asyncio.Future()
        request_item = RequestItem(
            priority=priority,
            func=func,
            future=future,
            created_at=time.time(),
            max_retries=max_retries
        )
        
        # Add to priority queue with manual tuple for comparison
        queue_item = (priority.value, request_item.created_at, id(request_item), request_item)
        await self.request_queue.put(queue_item)
        
        # Start processing if not already running
        if not self.is_processing:
            asyncio.create_task(self._process_queue())
        
        # Wait for result
        return await future
    
    async def _process_queue(self):
        """Process queued requests with rate limiting"""
        if self.is_processing:
            return
        
        self.is_processing = True
        logger.debug("🔄 Starting request queue processing")
        
        try:
            while not self.request_queue.empty():
                # Get next request (now with 4-tuple)
                _, _, _, request_item = await self.request_queue.get()
                
                try:
                    # Check rate limits before processing
                    await self.should_wait_before_request()
                    
                    # Execute request
                    start_time = time.time()
                    result = await request_item.func()
                    
                    # Mark as completed
                    if not request_item.future.done():
                        request_item.future.set_result(result)
                    
                    # Log metrics
                    response_time = time.time() - start_time
                    logger.debug(f"✅ Request completed in {response_time:.2f}s")
                    
                except Exception as e:
                    # Handle retry logic
                    request_item.retries += 1
                    
                    if request_item.retries < request_item.max_retries:
                        # Calculate backoff and retry
                        delay = self.calculate_backoff_delay(request_item.retries)
                        logger.warning(f"🔄 Retrying request in {delay:.1f}s (attempt {request_item.retries + 1})")
                        
                        await asyncio.sleep(delay)
                        retry_item = (request_item.priority.value, request_item.created_at, id(request_item), request_item)
                        await self.request_queue.put(retry_item)
                    else:
                        # Max retries exceeded
                        if not request_item.future.done():
                            request_item.future.set_exception(e)
                        logger.error(f"❌ Request failed after {request_item.max_retries} retries: {e}")
                
                # Small delay between requests to avoid overwhelming API
                await asyncio.sleep(0.1)
                
        finally:
            self.is_processing = False
            logger.debug("🏁 Request queue processing completed")
    
    @asynccontextmanager
    async def rate_limited_session(self):
        """Context manager for rate-limited sessions"""
        try:
            yield self
        finally:
            # Clean up any pending requests
            while not self.request_queue.empty():
                try:
                    _, _, _, request_item = self.request_queue.get_nowait()
                    if not request_item.future.done():
                        request_item.future.cancel()
                except asyncio.QueueEmpty:
                    break
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get current metrics and state"""
        return {
            "rate_limit_state": asdict(self.state),
            "circuit_breaker_active": time.time() < self.circuit_breaker_until,
            "consecutive_failures": self.consecutive_failures,
            "queue_size": self.request_queue.qsize(),
            "cache_entries": len(self.etag_cache)
        } 