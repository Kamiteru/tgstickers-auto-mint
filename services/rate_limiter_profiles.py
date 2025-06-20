"""
Rate Limiter Profiles System
Predefined configurations for different trading scenarios
"""

from dataclasses import dataclass
from typing import Dict, Any
import os
from utils.logger import logger


@dataclass
class RateLimiterProfile:
    """Rate limiter configuration profile"""
    name: str
    description: str
    max_delay: int
    preemptive_delay: int
    circuit_breaker_threshold: int
    circuit_breaker_timeout: int
    aggressive_backoff_multiplier: float
    collection_check_interval: int
    monitoring_interval: int
    price_cache_ttl: int
    max_retries_per_request: int
    request_timeout: int


# Predefined profiles for different scenarios
RATE_LIMITER_PROFILES: Dict[str, RateLimiterProfile] = {
    "safe": RateLimiterProfile(
        name="Safe Mode",
        description="Maximum protection, minimal risk of account blocking",
        max_delay=600,  # 10 minutes
        preemptive_delay=120,  # 2 minutes
        circuit_breaker_threshold=2,
        circuit_breaker_timeout=600,  # 10 minutes
        aggressive_backoff_multiplier=3.0,
        collection_check_interval=10,
        monitoring_interval=5,
        price_cache_ttl=60,
        max_retries_per_request=3,
        request_timeout=45
    ),
    
    "balanced": RateLimiterProfile(
        name="Balanced Mode",
        description="Good balance between speed and safety (default)",
        max_delay=300,  # 5 minutes
        preemptive_delay=60,
        circuit_breaker_threshold=3,
        circuit_breaker_timeout=300,  # 5 minutes
        aggressive_backoff_multiplier=2.0,
        collection_check_interval=5,
        monitoring_interval=2,
        price_cache_ttl=30,
        max_retries_per_request=5,
        request_timeout=30
    ),
    
    "fast": RateLimiterProfile(
        name="Fast Mode",
        description="Optimized for quick soldouts (2-6 minutes window)",
        max_delay=60,  # 1 minute
        preemptive_delay=10,
        circuit_breaker_threshold=5,
        circuit_breaker_timeout=120,  # 2 minutes
        aggressive_backoff_multiplier=1.5,
        collection_check_interval=2,
        monitoring_interval=1,
        price_cache_ttl=10,
        max_retries_per_request=4,
        request_timeout=20
    ),
    
    "aggressive": RateLimiterProfile(
        name="Aggressive Mode",
        description="High-speed purchases, higher risk",
        max_delay=30,
        preemptive_delay=5,
        circuit_breaker_threshold=7,
        circuit_breaker_timeout=60,  # 1 minute
        aggressive_backoff_multiplier=1.2,
        collection_check_interval=1,
        monitoring_interval=1,
        price_cache_ttl=5,
        max_retries_per_request=3,
        request_timeout=15
    ),
    
    "extreme": RateLimiterProfile(
        name="Extreme Mode",
        description="Maximum speed, maximum risk - use only in emergency",
        max_delay=15,
        preemptive_delay=2,
        circuit_breaker_threshold=10,
        circuit_breaker_timeout=30,
        aggressive_backoff_multiplier=1.1,
        collection_check_interval=1,
        monitoring_interval=1,
        price_cache_ttl=3,
        max_retries_per_request=2,
        request_timeout=10
    )
}


class RateLimiterProfileManager:
    """Manager for rate limiter profiles"""
    
    def __init__(self):
        self.current_profile_name = self._detect_profile()
        self.current_profile = RATE_LIMITER_PROFILES[self.current_profile_name]
        logger.info(f"🎛️ Rate Limiter Profile: {self.current_profile.name}")
        logger.info(f"📝 {self.current_profile.description}")
    
    def _detect_profile(self) -> str:
        """Detect profile from environment variable or command line"""
        # Check environment variable
        profile_name = os.getenv('RATE_LIMITER_PROFILE', 'balanced').lower()
        
        # Check command line arguments
        import sys
        for arg in sys.argv:
            if arg.startswith('--profile='):
                profile_name = arg.split('=')[1].lower()
            elif arg in ['--safe', '--balanced', '--fast', '--aggressive', '--extreme']:
                profile_name = arg[2:]  # Remove --
        
        # Validate profile name
        if profile_name not in RATE_LIMITER_PROFILES:
            logger.warning(f"❌ Unknown profile '{profile_name}', using 'balanced'")
            profile_name = 'balanced'
        
        return profile_name
    
    def get_profile(self) -> RateLimiterProfile:
        """Get current active profile"""
        return self.current_profile
    
    def list_profiles(self) -> Dict[str, str]:
        """Get list of available profiles with descriptions"""
        return {name: profile.description for name, profile in RATE_LIMITER_PROFILES.items()}
    
    def switch_profile(self, profile_name: str) -> bool:
        """Switch to different profile"""
        if profile_name.lower() not in RATE_LIMITER_PROFILES:
            logger.error(f"❌ Profile '{profile_name}' not found")
            return False
        
        self.current_profile_name = profile_name.lower()
        self.current_profile = RATE_LIMITER_PROFILES[self.current_profile_name]
        logger.info(f"🔄 Switched to profile: {self.current_profile.name}")
        return True
    
    def apply_to_settings(self, settings):
        """Apply current profile settings to app settings"""
        profile = self.current_profile
        
        # Rate limiter settings
        settings.rate_limiter_max_delay = profile.max_delay
        settings.rate_limiter_preemptive_delay = profile.preemptive_delay
        settings.rate_limiter_circuit_breaker_threshold = profile.circuit_breaker_threshold
        settings.rate_limiter_circuit_breaker_timeout = profile.circuit_breaker_timeout
        settings.rate_limiter_aggressive_backoff_multiplier = profile.aggressive_backoff_multiplier
        
        # API settings
        settings.collection_check_interval = profile.collection_check_interval
        settings.monitoring_interval = profile.monitoring_interval
        settings.price_cache_ttl = profile.price_cache_ttl
        settings.max_retries_per_request = profile.max_retries_per_request
        settings.request_timeout = profile.request_timeout
        
        logger.info(f"✅ Applied {profile.name} settings")
        self._log_profile_settings(profile)
    
    def _log_profile_settings(self, profile: RateLimiterProfile):
        """Log current profile settings"""
        logger.info("📋 Current Rate Limiter Settings:")
        logger.info(f"   🕒 Max delay: {profile.max_delay}s")
        logger.info(f"   ⚡ Preemptive delay: {profile.preemptive_delay}s")
        logger.info(f"   🚫 Circuit breaker: {profile.circuit_breaker_threshold} errors = {profile.circuit_breaker_timeout}s block")
        logger.info(f"   📊 Check intervals: collection={profile.collection_check_interval}s, monitoring={profile.monitoring_interval}s")
        logger.info(f"   🔄 Retries: {profile.max_retries_per_request}, timeout: {profile.request_timeout}s")


def print_available_profiles():
    """Print all available profiles for user reference"""
    print("\n🎛️  Available Rate Limiter Profiles:")
    print("=" * 60)
    
    for name, profile in RATE_LIMITER_PROFILES.items():
        risk_level = "🟢 Low" if name == "safe" else \
                    "🟡 Medium" if name in ["balanced", "fast"] else \
                    "🟠 High" if name == "aggressive" else "🔴 Very High"
        
        speed_level = "🐌 Slow" if name == "safe" else \
                     "🚶 Normal" if name == "balanced" else \
                     "🏃 Fast" if name == "fast" else \
                     "🏃‍♂️ Very Fast" if name == "aggressive" else "⚡ Lightning"
        
        print(f"\n🔸 {name.upper()}")
        print(f"   📝 {profile.description}")
        print(f"   ⚡ Speed: {speed_level}")
        print(f"   🛡️  Risk: {risk_level}")
        print(f"   🕒 Max delay: {profile.max_delay}s")
        print(f"   📊 Check interval: {profile.collection_check_interval}s")
    
    print("\n" + "=" * 60)
    print("💡 Usage:")
    print("   Environment: RATE_LIMITER_PROFILE=fast")
    print("   Command line: python main.py 2/19 --fast")
    print("   Or: python main.py 2/19 --profile=aggressive")


# Create global instance
profile_manager = RateLimiterProfileManager() 