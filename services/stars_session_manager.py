#!/usr/bin/env python3
"""
Stars Session Manager
Advanced session management for Telegram Stars payments
"""

import asyncio
import json
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from pathlib import Path

from utils.logger import logger
from config import settings


@dataclass
class StarsSessionStats:
    """Statistics for Stars payment session"""
    total_purchases: int = 0
    successful_purchases: int = 0
    failed_purchases: int = 0
    total_errors: int = 0
    session_start_time: float = 0.0
    last_purchase_time: float = 0.0
    last_error_time: float = 0.0
    consecutive_errors: int = 0
    average_response_time: float = 0.0
    error_types: Dict[str, int] = None
    
    def __post_init__(self):
        if self.error_types is None:
            self.error_types = {}


@dataclass
class StarsSessionState:
    """Current state of Stars payment session"""
    is_active: bool = False
    purchases_this_session: int = 0
    last_purchase_interval: float = 0.0
    adaptive_interval: float = 0.0
    cooldown_until: float = 0.0
    circuit_breaker_active: bool = False
    circuit_breaker_until: float = 0.0
    session_quality_score: float = 1.0  # 0.0 to 1.0


class StarsSessionManager:
    """Manages Stars payment sessions with adaptive optimization"""
    
    def __init__(self):
        self.stats = StarsSessionStats()
        self.state = StarsSessionState()
        self.state_file = Path("data/stars_session_state.json")
        self.purchase_history: List[Dict[str, Any]] = []
        self.max_history_size = 100
        
        # Initialize session
        self._load_state()
        self._initialize_session()
    
    def _initialize_session(self):
        """Initialize session state"""
        current_time = time.time()
        
        if self.stats.session_start_time == 0.0:
            self.stats.session_start_time = current_time
            logger.info("🌟 Starting new Stars payment session")
        
        # Reset adaptive interval to configured base
        self.state.adaptive_interval = settings.stars_purchase_interval
        
        # Check if we're in cooldown
        if self.state.cooldown_until > current_time:
            remaining = int(self.state.cooldown_until - current_time)
            logger.info(f"⏰ Session in cooldown for {remaining}s")
        
        # Check circuit breaker
        if self.state.circuit_breaker_until > current_time:
            remaining = int(self.state.circuit_breaker_until - current_time)
            logger.warning(f"🚨 Circuit breaker active for {remaining}s")
            self.state.circuit_breaker_active = True
    
    async def can_make_purchase(self) -> tuple[bool, str]:
        """Check if we can make a purchase now"""
        current_time = time.time()
        
        # Check circuit breaker
        if self.state.circuit_breaker_active:
            if current_time < self.state.circuit_breaker_until:
                remaining = int(self.state.circuit_breaker_until - current_time)
                return False, f"Circuit breaker active for {remaining}s"
            else:
                self.state.circuit_breaker_active = False
                logger.info("✅ Circuit breaker deactivated")
        
        # Check session cooldown
        if current_time < self.state.cooldown_until:
            remaining = int(self.state.cooldown_until - current_time)
            return False, f"Session cooldown for {remaining}s"
        
        # Check session limits
        if self.state.purchases_this_session >= settings.stars_max_purchases_per_session:
            return False, "Session purchase limit reached"
        
        # Check purchase interval
        if self.stats.last_purchase_time > 0:
            time_since_last = current_time - self.stats.last_purchase_time
            required_interval = self._calculate_adaptive_interval()
            
            if time_since_last < required_interval:
                remaining = required_interval - time_since_last
                return False, f"Purchase interval: wait {remaining:.1f}s"
        
        return True, "Ready for purchase"
    
    def _calculate_adaptive_interval(self) -> float:
        """Calculate adaptive purchase interval based on current conditions"""
        if not settings.stars_adaptive_limits:
            return settings.stars_purchase_interval
        
        base_interval = settings.stars_purchase_interval
        
        # Adjust based on session quality
        quality_multiplier = 2.0 - self.state.session_quality_score  # 1.0 to 2.0
        
        # Adjust based on consecutive errors
        error_multiplier = 1.0 + (self.stats.consecutive_errors * 0.5)
        
        # Adjust based on recent error rate
        recent_error_rate = self._calculate_recent_error_rate()
        error_rate_multiplier = 1.0 + (recent_error_rate * 2.0)
        
        adaptive_interval = base_interval * quality_multiplier * error_multiplier * error_rate_multiplier
        
        # Clamp to configured limits
        min_interval = getattr(settings, 'stars_min_interval', 1.0)
        max_interval = getattr(settings, 'stars_max_interval', 10.0)
        
        adaptive_interval = max(min_interval, min(max_interval, adaptive_interval))
        
        self.state.adaptive_interval = adaptive_interval
        return adaptive_interval
    
    def _calculate_recent_error_rate(self) -> float:
        """Calculate error rate from recent purchase history"""
        if len(self.purchase_history) < 5:
            return 0.0
        
        # Look at last 10 purchases
        recent_purchases = self.purchase_history[-10:]
        errors = sum(1 for p in recent_purchases if not p.get('success', False))
        
        return errors / len(recent_purchases)
    
    async def record_purchase_attempt(self, success: bool, response_time: float = 0.0, error_type: str = None):
        """Record a purchase attempt and update session state"""
        current_time = time.time()
        
        # Update stats
        self.stats.total_purchases += 1
        self.stats.last_purchase_time = current_time
        
        if success:
            self.stats.successful_purchases += 1
            self.stats.consecutive_errors = 0
            self.state.purchases_this_session += 1
            
            # Update quality score positively
            self.state.session_quality_score = min(1.0, self.state.session_quality_score + 0.1)
            
            logger.info(f"✅ Stars purchase recorded: {self.state.purchases_this_session}/{settings.stars_max_purchases_per_session}")
            
        else:
            self.stats.failed_purchases += 1
            self.stats.total_errors += 1
            self.stats.consecutive_errors += 1
            self.stats.last_error_time = current_time
            
            # Record error type
            if error_type:
                self.stats.error_types[error_type] = self.stats.error_types.get(error_type, 0) + 1
            
            # Update quality score negatively
            self.state.session_quality_score = max(0.0, self.state.session_quality_score - 0.2)
            
            # Check if we need to activate circuit breaker
            await self._check_circuit_breaker()
            
            logger.warning(f"❌ Stars purchase failed: {self.stats.consecutive_errors} consecutive errors")
        
        # Update average response time
        if response_time > 0:
            if self.stats.average_response_time == 0:
                self.stats.average_response_time = response_time
            else:
                self.stats.average_response_time = (self.stats.average_response_time * 0.8) + (response_time * 0.2)
        
        # Add to history
        self.purchase_history.append({
            'timestamp': current_time,
            'success': success,
            'response_time': response_time,
            'error_type': error_type,
            'session_purchases': self.state.purchases_this_session,
            'quality_score': self.state.session_quality_score
        })
        
        # Limit history size
        if len(self.purchase_history) > self.max_history_size:
            self.purchase_history = self.purchase_history[-self.max_history_size:]
        
        # Check if session should be cooled down
        await self._check_session_cooldown()
        
        # Save state
        self._save_state()
    
    async def _check_circuit_breaker(self):
        """Check if circuit breaker should be activated"""
        # Activate circuit breaker on too many consecutive errors
        if self.stats.consecutive_errors >= 3:
            cooldown_time = 60 * (self.stats.consecutive_errors - 2)  # 60s, 120s, 180s, etc.
            self.state.circuit_breaker_until = time.time() + cooldown_time
            self.state.circuit_breaker_active = True
            
            logger.warning(f"🚨 Stars circuit breaker activated for {cooldown_time}s due to {self.stats.consecutive_errors} consecutive errors")
    
    async def _check_session_cooldown(self):
        """Check if session should enter cooldown"""
        # Enter cooldown if we've reached session limits
        if self.state.purchases_this_session >= settings.stars_max_purchases_per_session:
            self.state.cooldown_until = time.time() + settings.stars_session_cooldown
            logger.info(f"⏰ Session cooldown activated for {settings.stars_session_cooldown}s (limit reached)")
    
    def get_session_info(self) -> Dict[str, Any]:
        """Get current session information"""
        current_time = time.time()
        session_duration = current_time - self.stats.session_start_time
        
        success_rate = 0.0
        if self.stats.total_purchases > 0:
            success_rate = self.stats.successful_purchases / self.stats.total_purchases
        
        return {
            'session_active': self.state.is_active,
            'purchases_this_session': self.state.purchases_this_session,
            'max_purchases_per_session': settings.stars_max_purchases_per_session,
            'session_duration_minutes': session_duration / 60,
            'total_purchases': self.stats.total_purchases,
            'successful_purchases': self.stats.successful_purchases,
            'failed_purchases': self.stats.failed_purchases,
            'success_rate': success_rate,
            'consecutive_errors': self.stats.consecutive_errors,
            'quality_score': self.state.session_quality_score,
            'adaptive_interval': self.state.adaptive_interval,
            'circuit_breaker_active': self.state.circuit_breaker_active,
            'average_response_time': self.stats.average_response_time,
            'error_types': self.stats.error_types
        }
    
    def reset_session(self):
        """Reset current session state"""
        logger.info("🔄 Resetting Stars payment session")
        
        # Reset session-specific state
        self.state.purchases_this_session = 0
        self.state.cooldown_until = 0.0
        self.state.session_quality_score = 1.0
        self.stats.consecutive_errors = 0
        
        # Keep overall stats but reset session timer
        self.stats.session_start_time = time.time()
        
        self._save_state()
    
    def _save_state(self):
        """Save session state to file"""
        try:
            # Ensure data directory exists
            self.state_file.parent.mkdir(exist_ok=True)
            
            state_data = {
                'stats': asdict(self.stats),
                'state': asdict(self.state),
                'purchase_history': self.purchase_history[-20:]  # Save last 20 entries
            }
            
            with open(self.state_file, 'w') as f:
                json.dump(state_data, f, indent=2)
                
        except Exception as e:
            logger.error(f"Failed to save Stars session state: {e}")
    
    def _load_state(self):
        """Load session state from file"""
        try:
            if self.state_file.exists():
                with open(self.state_file, 'r') as f:
                    data = json.load(f)
                
                # Load stats
                if 'stats' in data:
                    stats_data = data['stats']
                    self.stats = StarsSessionStats(**stats_data)
                
                # Load state
                if 'state' in data:
                    state_data = data['state']
                    self.state = StarsSessionState(**state_data)
                
                # Load history
                if 'purchase_history' in data:
                    self.purchase_history = data['purchase_history']
                
                logger.info("📊 Stars session state loaded")
                
        except Exception as e:
            logger.warning(f"Could not load Stars session state: {e}")
            # Initialize with defaults
            self.stats = StarsSessionStats()
            self.state = StarsSessionState()


# Global instance
_stars_session_manager = None


def get_stars_session_manager() -> StarsSessionManager:
    """Get the global Stars session manager instance"""
    global _stars_session_manager
    if _stars_session_manager is None:
        _stars_session_manager = StarsSessionManager()
    return _stars_session_manager 