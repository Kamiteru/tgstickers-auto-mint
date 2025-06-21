import os
from dataclasses import dataclass, field
from dotenv import load_dotenv
from exceptions import ConfigError

# Load environment variables from .env file
load_dotenv()


class Settings:
    """Application configuration settings"""
    
    def __init__(self):
        load_dotenv()
        
        # Apply rate limiter profile before loading config
        self._apply_rate_limiter_profile()
        
        # Apply stars profile before loading config
        self._apply_stars_profile()
        
        # Core API Configuration
        self.stickerdom_jwt_token = os.getenv('STICKERDOM_JWT_TOKEN')
        self.api_base_url = os.getenv('API_BASE_URL', 'https://api.stickerdom.store')
        self.jwt_token = self.stickerdom_jwt_token  # Legacy compatibility
        self.payment_methods = [method.strip() for method in os.getenv('PAYMENT_METHODS', 'TON,STARS').split(',')]
        
        # TON Blockchain Configuration
        self.ton_seed_phrase = os.getenv('TON_SEED_PHRASE')
        self.ton_endpoint = os.getenv('TON_ENDPOINT', 'mainnet')
        
        # Telegram Stars Payment Configuration
        self.telegram_api_id = int(os.getenv('TELEGRAM_API_ID', 0))
        self.telegram_api_hash = os.getenv('TELEGRAM_API_HASH', '')
        self.telegram_phone = os.getenv('TELEGRAM_PHONE', '')
        self.telegram_session_name = os.getenv('TELEGRAM_SESSION_NAME', 'stars_payment_session')
        
        # Stars Advanced Configuration
        self.stars_max_purchases_per_session = int(os.getenv('STARS_MAX_PURCHASES_PER_SESSION', 3))
        self.stars_purchase_interval = float(os.getenv('STARS_PURCHASE_INTERVAL', 2.0))
        self.stars_session_cooldown = int(os.getenv('STARS_SESSION_COOLDOWN', 30))
        self.stars_max_retry_attempts = int(os.getenv('STARS_MAX_RETRY_ATTEMPTS', 3))
        self.stars_adaptive_limits = os.getenv('STARS_ADAPTIVE_LIMITS', 'true').lower() == 'true'
        self.stars_concurrent_purchases = os.getenv('STARS_CONCURRENT_PURCHASES', 'false').lower() == 'true'
        self.stars_payment_timeout = int(os.getenv('STARS_PAYMENT_TIMEOUT', 120))
        self.stars_invoice_timeout = int(os.getenv('STARS_INVOICE_TIMEOUT', 30))
        self.stars_profile = os.getenv('STARS_PROFILE', 'balanced')  # conservative/balanced/aggressive
        
        # CAPTCHA Configuration
        self.captcha_enabled = os.getenv('CAPTCHA_ENABLED', 'true').lower() == 'true'
        self.anticaptcha_api_key = os.getenv('ANTICAPTCHA_API_KEY')
        self.captcha_timeout = int(os.getenv('CAPTCHA_TIMEOUT', 300))
        
        # Rate Limiter Configuration
        self.rate_limiter_enabled = os.getenv('RATE_LIMITER_ENABLED', 'true').lower() == 'true'
        self.rate_limiter_db_path = os.getenv('RATE_LIMITER_DB_PATH', 'data/rate_limiter.db')
        self.rate_limiter_max_delay = int(os.getenv('RATE_LIMITER_MAX_DELAY', 300))
        self.rate_limiter_circuit_breaker_threshold = int(os.getenv('RATE_LIMITER_CIRCUIT_BREAKER_THRESHOLD', 3))
        self.rate_limiter_circuit_breaker_timeout = int(os.getenv('RATE_LIMITER_CIRCUIT_BREAKER_TIMEOUT', 300))
        self.rate_limiter_preemptive_delay = int(os.getenv('RATE_LIMITER_PREEMPTIVE_DELAY', 60))
        self.rate_limiter_aggressive_backoff_multiplier = float(os.getenv('RATE_LIMITER_AGGRESSIVE_BACKOFF_MULTIPLIER', 2.0))
        
        # Notification System Configuration
        self.telegram_bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
        self.telegram_chat_id = os.getenv('TELEGRAM_CHAT_ID')
        
        # Proxy Configuration for IP ban bypass
        self.proxy_enabled = os.getenv('PROXY_ENABLED', 'false').lower() == 'true'
        self.proxy_url = os.getenv('PROXY_URL', '')  # http://user:pass@host:port or socks5://host:port
        self.user_agent_rotation = os.getenv('USER_AGENT_ROTATION', 'true').lower() == 'true'
        
        # API Client Configuration
        self.request_timeout = int(os.getenv('REQUEST_TIMEOUT', 30))
        self.max_retries_per_request = int(os.getenv('MAX_RETRIES_PER_REQUEST', 5))
        self.price_cache_ttl = int(os.getenv('PRICE_CACHE_TTL', 30))
        self.collection_check_interval = int(os.getenv('COLLECTION_CHECK_INTERVAL', 5))
        self.collection_not_found_retry = int(os.getenv('COLLECTION_NOT_FOUND_RETRY', 30))
        
        # Logging Configuration
        self.log_level = os.getenv('LOG_LEVEL', 'INFO')
        self.log_to_file = os.getenv('LOG_TO_FILE', 'true').lower() == 'true'
        self.log_file_path = os.getenv('LOG_FILE_PATH', 'logs/sticker_bot.log')
        
        # Advanced Settings
        self.dry_run_mode = os.getenv('DRY_RUN_MODE', 'false').lower() == 'true'
        self.test_mode = os.getenv('TEST_MODE', 'false').lower() == 'true'
        self.monitoring_interval = int(os.getenv('MONITORING_INTERVAL', 1))
        
        # Endpoint discovery settings
        self.selenium_headless_disabled = os.getenv('SELENIUM_HEADLESS_DISABLED', 'False').lower() == 'true'
        self.endpoint_validation_enabled = os.getenv('ENDPOINT_VALIDATION_ENABLED', 'True').lower() == 'true'
        self.endpoint_validation_timeout = float(os.getenv('ENDPOINT_VALIDATION_TIMEOUT', '2.0'))
        
        # Legacy compatibility
        self.stickers_per_purchase = 5  # Fixed value for current implementation
        self.gas_amount = 0.1  # Standard TON gas amount

    def validate(self):
        """Validate required configuration"""
        if not self.stickerdom_jwt_token:
            raise ConfigError("STICKERDOM_JWT_TOKEN environment variable is required")
        
        # Validate payment methods
        valid_methods = ['TON', 'STARS']
        if not self.payment_methods:
            raise ConfigError("At least one payment method must be specified in PAYMENT_METHODS")
        
        for method in self.payment_methods:
            if method not in valid_methods:
                raise ConfigError(f"Invalid payment method '{method}'. Must be one of: {', '.join(valid_methods)}")
        
        # Validate method-specific requirements
        if 'TON' in self.payment_methods:
            if not self.ton_seed_phrase:
                raise ConfigError("TON_SEED_PHRASE environment variable is required for TON payments")
        
        if 'STARS' in self.payment_methods:
            if not self.telegram_api_id:
                raise ConfigError("TELEGRAM_API_ID environment variable is required for Stars payments")
            if not self.telegram_api_hash:
                raise ConfigError("TELEGRAM_API_HASH environment variable is required for Stars payments")
            if not self.telegram_phone:
                raise ConfigError("TELEGRAM_PHONE environment variable is required for Stars payments")
                
        if self.stickers_per_purchase <= 0:
            raise ConfigError("STICKERS_PER_PURCHASE must be positive")
        if self.gas_amount <= 0:
            raise ConfigError("GAS_AMOUNT must be positive")
    
    def _apply_rate_limiter_profile(self):
        """Apply rate limiter profile settings if available"""
        try:
            from services.rate_limiter_profiles import profile_manager
            # Profile manager will be applied after config loading
            self._profile_manager = profile_manager
        except ImportError:
            # Profiles not available, use defaults
            self._profile_manager = None
    
    def _apply_stars_profile(self):
        """Apply stars profile settings if available"""
        try:
            from services.stars_profiles import stars_profile_manager
            # Stars profile manager will be applied after config loading
            self._stars_profile_manager = stars_profile_manager
        except ImportError:
            # Profiles not available, use defaults
            self._stars_profile_manager = None
    
    def apply_profile_overrides(self):
        """Apply profile overrides after config is loaded"""
        if hasattr(self, '_profile_manager') and self._profile_manager:
            self._profile_manager.apply_to_settings(self)
        
        if hasattr(self, '_stars_profile_manager') and self._stars_profile_manager:
            self._stars_profile_manager.apply_to_settings(self)

    @property
    def payment_method(self) -> str:
        """Backward compatibility property - returns first payment method"""
        return self.payment_methods[0] if self.payment_methods else 'STARS'


# Create settings instance
settings = Settings()

# Apply profile overrides after settings are created
settings.apply_profile_overrides()