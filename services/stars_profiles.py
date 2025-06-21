#!/usr/bin/env python3
"""
Stars Profile Manager
Configurable profiles for Telegram Stars payment optimization
"""

import argparse
import sys
from typing import Dict, Any, Optional
from dataclasses import dataclass
from utils.logger import logger


@dataclass
class StarsProfile:
    """Profile configuration for Stars payments"""
    name: str
    description: str
    max_purchases_per_session: int
    purchase_interval: float
    session_cooldown: int
    max_retry_attempts: int
    payment_timeout: int
    invoice_timeout: int
    adaptive_limits: bool
    concurrent_purchases: bool
    backoff_multiplier: float = 1.5
    min_interval: float = 1.0
    max_interval: float = 10.0


class StarsProfileManager:
    """Manager for Stars payment profiles"""
    
    def __init__(self):
        self.profiles = self._create_default_profiles()
        self.active_profile = None
        self._applied_to_settings = False
    
    def _create_default_profiles(self) -> Dict[str, StarsProfile]:
        """Create default Stars profiles"""
        return {
            'conservative': StarsProfile(
                name='Conservative Mode',
                description='Minimum risk, maximum safety for Stars payments',
                max_purchases_per_session=2,
                purchase_interval=5.0,
                session_cooldown=60,
                max_retry_attempts=2,
                payment_timeout=180,
                invoice_timeout=45,
                adaptive_limits=True,
                concurrent_purchases=False,
                backoff_multiplier=2.0,
                min_interval=3.0,
                max_interval=15.0
            ),
            'balanced': StarsProfile(
                name='Balanced Mode',
                description='Good balance between speed and safety for Stars (default)',
                max_purchases_per_session=3,
                purchase_interval=2.0,
                session_cooldown=30,
                max_retry_attempts=3,
                payment_timeout=120,
                invoice_timeout=30,
                adaptive_limits=True,
                concurrent_purchases=False,
                backoff_multiplier=1.5,
                min_interval=1.0,
                max_interval=10.0
            ),
            'aggressive': StarsProfile(
                name='Aggressive Mode',
                description='Fast Stars purchases with higher risk tolerance',
                max_purchases_per_session=5,
                purchase_interval=1.0,
                session_cooldown=15,
                max_retry_attempts=4,
                payment_timeout=90,
                invoice_timeout=20,
                adaptive_limits=True,
                concurrent_purchases=True,
                backoff_multiplier=1.2,
                min_interval=0.5,
                max_interval=5.0
            ),
            'extreme': StarsProfile(
                name='Extreme Mode',
                description='Maximum speed Stars purchases (high risk)',
                max_purchases_per_session=8,
                purchase_interval=0.5,
                session_cooldown=10,
                max_retry_attempts=5,
                payment_timeout=60,
                invoice_timeout=15,
                adaptive_limits=False,
                concurrent_purchases=True,
                backoff_multiplier=1.1,
                min_interval=0.2,
                max_interval=3.0
            )
        }
    
    def get_profile(self, profile_name: str) -> Optional[StarsProfile]:
        """Get profile by name"""
        return self.profiles.get(profile_name.lower())
    
    def set_active_profile(self, profile_name: str) -> bool:
        """Set active profile"""
        profile = self.get_profile(profile_name)
        if profile:
            self.active_profile = profile
            logger.info(f"🌟 Stars Profile: {profile.name}")
            logger.info(f"📝 {profile.description}")
            return True
        return False
    
    def apply_to_settings(self, settings):
        """Apply active profile to settings"""
        if not self.active_profile:
            # Try to determine profile from command line or environment
            self._detect_profile_from_args()
            if not self.active_profile:
                # Default to balanced
                self.set_active_profile('balanced')
        
        if self.active_profile and not self._applied_to_settings:
            profile = self.active_profile
            
            # Apply profile settings
            settings.stars_max_purchases_per_session = profile.max_purchases_per_session
            settings.stars_purchase_interval = profile.purchase_interval
            settings.stars_session_cooldown = profile.session_cooldown
            settings.stars_max_retry_attempts = profile.max_retry_attempts
            settings.stars_payment_timeout = profile.payment_timeout
            settings.stars_invoice_timeout = profile.invoice_timeout
            settings.stars_adaptive_limits = profile.adaptive_limits
            settings.stars_concurrent_purchases = profile.concurrent_purchases
            
            # Add profile-specific settings
            settings.stars_backoff_multiplier = profile.backoff_multiplier
            settings.stars_min_interval = profile.min_interval
            settings.stars_max_interval = profile.max_interval
            
            logger.info(f"🎛️ Active Stars Profile: {profile.name}")
            logger.info(f"   📝 {profile.description}")
            logger.info(f"   💫 Max purchases: {profile.max_purchases_per_session}, Interval: {profile.purchase_interval}s")
            
            self._applied_to_settings = True
    
    def _detect_profile_from_args(self):
        """Detect profile from command line arguments or environment"""
        # Check command line arguments
        if '--stars-conservative' in sys.argv:
            self.set_active_profile('conservative')
        elif '--stars-balanced' in sys.argv:
            self.set_active_profile('balanced')
        elif '--stars-aggressive' in sys.argv:
            self.set_active_profile('aggressive')
        elif '--stars-extreme' in sys.argv:
            self.set_active_profile('extreme')
        else:
            # Check environment variable
            import os
            profile_name = os.getenv('STARS_PROFILE', 'balanced')
            self.set_active_profile(profile_name)
    
    def get_current_profile_info(self) -> Dict[str, Any]:
        """Get current profile information"""
        if not self.active_profile:
            return {}
        
        profile = self.active_profile
        return {
            'name': profile.name,
            'description': profile.description,
            'max_purchases_per_session': profile.max_purchases_per_session,
            'purchase_interval': profile.purchase_interval,
            'session_cooldown': profile.session_cooldown,
            'adaptive_limits': profile.adaptive_limits,
            'concurrent_purchases': profile.concurrent_purchases
        }
    
    def list_profiles(self) -> Dict[str, str]:
        """List all available profiles"""
        return {name: profile.description for name, profile in self.profiles.items()}


# Global instance
stars_profile_manager = StarsProfileManager()


def get_stars_profile_manager() -> StarsProfileManager:
    """Get the global Stars profile manager instance"""
    return stars_profile_manager


# Command line interface for testing
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Stars Profile Manager')
    parser.add_argument('--list', action='store_true', help='List all profiles')
    parser.add_argument('--profile', type=str, help='Show specific profile details')
    
    args = parser.parse_args()
    
    if args.list:
        print("Available Stars Profiles:")
        for name, desc in stars_profile_manager.list_profiles().items():
            print(f"  {name}: {desc}")
    elif args.profile:
        profile = stars_profile_manager.get_profile(args.profile)
        if profile:
            print(f"Profile: {profile.name}")
            print(f"Description: {profile.description}")
            print(f"Max purchases per session: {profile.max_purchases_per_session}")
            print(f"Purchase interval: {profile.purchase_interval}s")
            print(f"Session cooldown: {profile.session_cooldown}s")
            print(f"Adaptive limits: {profile.adaptive_limits}")
            print(f"Concurrent purchases: {profile.concurrent_purchases}")
        else:
            print(f"Profile '{args.profile}' not found")
    else:
        parser.print_help() 