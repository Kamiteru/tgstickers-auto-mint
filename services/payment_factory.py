from typing import Dict, Optional

from services.api_client import StickerdomAPI
from services.ton_wallet import TONWalletManager
from services.telegram_stars import TelegramStarsPayment
from services.cache_manager import StateCache
from services.payment_strategies import PaymentStrategy, TONPaymentStrategy, StarsPaymentStrategy
from services.validators import PurchaseValidator
from exceptions import APIError
from config import settings
from utils.logger import logger


class PaymentMethodFactory:
    """Factory for creating payment strategy instances"""
    
    def __init__(
        self,
        api_client: StickerdomAPI,
        wallet_manager: Optional[TONWalletManager] = None,
        stars_payment: Optional[TelegramStarsPayment] = None,
        cache_manager: Optional[StateCache] = None
    ):
        self.api_client = api_client
        self.wallet_manager = wallet_manager
        self.stars_payment = stars_payment
        self.cache_manager = cache_manager
        self.validator = PurchaseValidator()
        
        # Validate required dependencies
        self._validate_dependencies()
    
    def _validate_dependencies(self):
        """Validate that required dependencies are available for configured payment methods"""
        if 'TON' in settings.payment_methods and not self.wallet_manager:
            raise APIError("TON payment method enabled but wallet_manager not provided")
        
        if 'STARS' in settings.payment_methods and not self.stars_payment:
            raise APIError("STARS payment method enabled but stars_payment not provided")
    
    def create_strategy(self, method: str) -> PaymentStrategy:
        """Create payment strategy instance for given method"""
        # Validate method
        method = self.validator.validate_payment_method(method)
        
        if method == 'TON':
            if not self.wallet_manager:
                raise APIError("TON wallet manager not available")
            
            return TONPaymentStrategy(
                api_client=self.api_client,
                wallet_manager=self.wallet_manager,
                cache_manager=self.cache_manager
            )
        
        elif method == 'STARS':
            if not self.stars_payment:
                raise APIError("Stars payment service not available")
            
            return StarsPaymentStrategy(
                api_client=self.api_client,
                stars_payment=self.stars_payment,
                cache_manager=self.cache_manager
            )
        
        else:
            raise APIError(f"Unknown payment method: {method}")
    
    def create_all_strategies(self) -> Dict[str, PaymentStrategy]:
        """Create all configured payment strategies"""
        strategies = {}
        
        for method in settings.payment_methods:
            try:
                strategy = self.create_strategy(method)
                strategies[method] = strategy
                logger.info(f"Created {method} payment strategy")
            except Exception as e:
                logger.error(f"Failed to create {method} payment strategy: {e}")
                # Don't raise, allow other strategies to be created
        
        if not strategies:
            raise APIError("No payment strategies could be created")
        
        return strategies
    
    def get_available_methods(self) -> list[str]:
        """Get list of available payment methods based on dependencies"""
        available = []
        
        for method in settings.payment_methods:
            try:
                if method == 'TON' and self.wallet_manager:
                    available.append(method)
                elif method == 'STARS' and self.stars_payment:
                    available.append(method)
            except Exception as e:
                logger.warning(f"Method {method} not available: {e}")
        
        return available 