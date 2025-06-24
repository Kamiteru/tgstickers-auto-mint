import os
from dataclasses import dataclass, field
from dotenv import load_dotenv
from exceptions import ConfigError

# Load environment variables from .env file
load_dotenv()

@dataclass
class Config:
    
    # Security: load from environment variables
    jwt_token: str = os.getenv('STICKERDOM_JWT_TOKEN', '')
    ton_seed_phrase: str = os.getenv('TON_SEED_PHRASE', '')
    
    # Payment methods selection (can be multiple, comma-separated)
    payment_methods: list = field(default_factory=lambda: [method.strip().upper() for method in os.getenv('PAYMENT_METHODS', 'STARS').split(',')])
    
    # Telegram bot settings for Stars payments (legacy)
    telegram_bot_token_payment: str = os.getenv('TELEGRAM_BOT_TOKEN_PAYMENT', '')
    telegram_chat_id_payment: str = os.getenv('TELEGRAM_CHAT_ID_PAYMENT', '')
    
    # Telethon settings for Stars payments (new method)
    telegram_api_id: int = int(os.getenv('TELEGRAM_API_ID', '0'))
    telegram_api_hash: str = os.getenv('TELEGRAM_API_HASH', '')
    telegram_phone: str = os.getenv('TELEGRAM_PHONE', '')
    telegram_session_name: str = os.getenv('TELEGRAM_SESSION_NAME', 'stars_payment_session')
    
    # Trading settings
    gas_amount: float = float(os.getenv('GAS_AMOUNT', '0.1'))
    purchase_delay: int = int(os.getenv('PURCHASE_DELAY', '1'))
    
    # Monitoring settings
    collection_check_interval: int = int(os.getenv('COLLECTION_CHECK_INTERVAL', '1'))
    collection_not_found_retry: int = int(os.getenv('COLLECTION_NOT_FOUND_RETRY', '3'))
    max_retries_per_request: int = int(os.getenv('MAX_RETRIES_PER_REQUEST', '5'))
    request_timeout: int = int(os.getenv('REQUEST_TIMEOUT', '10'))
    
    # Performance cache settings
    cache_balance_interval: float = float(os.getenv('CACHE_BALANCE_INTERVAL', '2.0'))  # Balance refresh interval in seconds
    cache_price_interval: float = float(os.getenv('CACHE_PRICE_INTERVAL', '10.0'))    # Price refresh interval in seconds
    
    # Captcha settings
    captcha_enabled: bool = os.getenv('CAPTCHA_ENABLED', 'true').lower() == 'true'
    anticaptcha_api_key: str = os.getenv('ANTICAPTCHA_API_KEY', '')
    captcha_timeout: int = int(os.getenv('CAPTCHA_TIMEOUT', '300'))  # 5 minutes timeout
    
    # Constants
    api_base_url: str = "https://api.stickerdom.store"
    ton_endpoint: str = os.getenv('TON_ENDPOINT', 'mainnet')  # mainnet or testnet
    
    def reload_env(self):
        """Reload environment variables from .env file"""
        load_dotenv(override=True)
        
        # Update only the JWT token from refreshed environment
        new_token = os.getenv('STICKERDOM_JWT_TOKEN', '')
        if new_token and new_token != self.jwt_token:
            print(f"🔄 Updating JWT token in config")
            self.jwt_token = new_token
            return True
        return False

    
    def validate(self):
        """Validate required configuration"""
        if not self.jwt_token:
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
                
        if self.gas_amount <= 0:
            raise ConfigError("GAS_AMOUNT must be positive")
    
    @property
    def payment_method(self) -> str:
        """Backward compatibility property - returns first payment method"""
        return self.payment_methods[0] if self.payment_methods else 'STARS'


settings = Config()