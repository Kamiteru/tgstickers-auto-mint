import asyncio
import time
from abc import ABC, abstractmethod
from datetime import datetime
from decimal import Decimal
from typing import Optional

from services.api_client import StickerdomAPI
from services.ton_wallet import TONWalletManager
from services.telegram_stars import TelegramStarsPayment
from services.cache_manager import StateCache
from services.validators import PurchaseValidator, SecurityValidator
from services.rate_limiter import RequestPriority
from models import PurchaseRequest, PurchaseResult, PurchaseStatus
from exceptions import (
    InsufficientBalanceError, CollectionNotAvailableError, APIError
)
from config import settings
from utils.logger import logger


class PaymentStrategy(ABC):
    """Abstract base class for payment strategies"""
    
    def __init__(self, api_client: StickerdomAPI, cache_manager: Optional[StateCache] = None):
        self.api = api_client
        self.cache = cache_manager
        self.validator = PurchaseValidator()
        self.security_validator = SecurityValidator()
    
    @abstractmethod
    async def execute_purchase(
        self,
        collection_id: int,
        character_id: int,
        count: int
    ) -> PurchaseResult:
        """Execute a single purchase using this payment method"""
        pass
    
    @abstractmethod
    async def calculate_max_purchases(
        self,
        collection_id: int,
        character_id: int,
        stickers_per_purchase: int
    ) -> tuple[int, float]:
        """Calculate maximum possible purchases with this payment method"""
        pass
    
    @abstractmethod
    def get_method_name(self) -> str:
        """Get payment method name"""
        pass


class TONPaymentStrategy(PaymentStrategy):
    """TON blockchain payment strategy"""
    
    def __init__(self, api_client: StickerdomAPI, wallet_manager: TONWalletManager, cache_manager: Optional[StateCache] = None):
        super().__init__(api_client, cache_manager)
        self.wallet = wallet_manager
    
    def get_method_name(self) -> str:
        return "TON"
    
    async def calculate_max_purchases(
        self,
        collection_id: int,
        character_id: int,
        stickers_per_purchase: int
    ) -> tuple[int, float]:
        """Calculate maximum TON purchases based on wallet balance"""
        # Validate inputs
        self.validator.validate_purchase_params(collection_id, character_id, stickers_per_purchase)
        
        # Get character price
        if self.cache:
            character_price_ton = await self.cache.get_cached_price(collection_id, character_id)
        else:
            character_price_ton = await self.api.get_character_price(
                collection_id, character_id, "TON", priority=RequestPriority.CRITICAL
            )
        
        # Validate price
        character_price_ton = self.validator.validate_price_data(
            character_price_ton, collection_id, character_id
        )
        
        # Get wallet balance
        if self.cache:
            wallet_info = await self.cache.get_cached_balance()
        else:
            wallet_info = await self.wallet.get_wallet_info()
        
        # Calculate max purchases with validation
        return self.validator.validate_max_purchases_calculation(
            wallet_info.balance_ton,
            character_price_ton,
            stickers_per_purchase
        )
    
    async def execute_purchase(
        self,
        collection_id: int,
        character_id: int,
        count: int
    ) -> PurchaseResult:
        """Execute TON purchase with comprehensive validation"""
        purchase_request = None
        
        try:
            # Input validation
            self.validator.validate_purchase_params(collection_id, character_id, count)
            
            # Validate collection and character availability
            collection = await self.api.get_collection(collection_id, priority=RequestPriority.HIGH)
            if not collection or not collection.is_active:
                raise CollectionNotAvailableError(f"Collection {collection_id} not available")

            character = next((c for c in collection.characters if c.id == character_id), None)
            if not character:
                raise CollectionNotAvailableError(f"Character {character_id} not found")
            
            # Validate and adjust count based on availability
            count = self.validator.validate_character_availability(character, count)
            
            # Get current price with validation
            if self.cache:
                character_price_ton = await self.cache.get_cached_price(collection_id, character_id)
            else:
                character_price_ton = await self.api.get_character_price(
                    collection_id, character_id, "TON", priority=RequestPriority.CRITICAL
                )
            
            character_price_ton = self.validator.validate_price_data(
                character_price_ton, collection_id, character_id
            )
            
            # Security validation
            await self.security_validator.validate_with_timeout(
                self.security_validator.validate_transaction_limits,
                30.0,  # 30 second timeout
                character_price_ton
            )
            
            # Check wallet balance with race condition protection
            if self.cache:
                wallet_info = await self.cache.get_cached_balance()
            else:
                wallet_info = await self.wallet.get_wallet_info()
            
            # Validate balance
            self.validator.validate_balance_calculation(
                wallet_info.balance_ton,
                character_price_ton
            )
            
            # Initiate purchase through API
            purchase_data = await asyncio.wait_for(
                self.api.initiate_purchase(collection_id, character_id, count),
                timeout=30.0  # 30 second timeout
            )
            
            # Create purchase request
            purchase_request = PurchaseRequest(
                collection_id=collection_id,
                character_id=character_id,
                count=count,
                price_per_item=character_price_ton / count,  # Convert pack price to per-sticker
                total_amount=Decimal(purchase_data['total_amount']),
                order_id=purchase_data['order_id'],
                destination_wallet=purchase_data['wallet'],
                created_at=datetime.now()
            )
            
            # Final balance check before sending (race condition protection)
            final_wallet_info = await self.wallet.get_wallet_info()
            self.validator.validate_balance_calculation(
                final_wallet_info.balance_ton,
                character_price_ton
            )
            
            # Send payment with timeout
            tx_hash, completed_at = await asyncio.wait_for(
                self.wallet.send_payment(
                    destination=purchase_request.destination_wallet,
                    amount_nano=int(purchase_request.total_amount),
                    comment=purchase_request.order_id
                ),
                timeout=60.0  # 60 second timeout for blockchain transaction
            )
            
            result = PurchaseResult(
                request=purchase_request,
                transaction_hash=tx_hash,
                status=PurchaseStatus.CONFIRMED,
                completed_at=completed_at
            )
            
            logger.info(f"TON purchase completed successfully: {tx_hash}")
            return result
            
        except asyncio.TimeoutError:
            error_msg = "Purchase timed out"
            logger.error(error_msg)
            
            if purchase_request:
                return PurchaseResult(
                    request=purchase_request,
                    transaction_hash=None,
                    status=PurchaseStatus.TIMEOUT,
                    completed_at=datetime.now(),
                    error_message=error_msg
                )
            raise APIError(error_msg)
            
        except (APIError, CollectionNotAvailableError, InsufficientBalanceError) as e:
            logger.error(f"TON purchase failed: {e}")
            
            if purchase_request:
                return PurchaseResult(
                    request=purchase_request,
                    transaction_hash=None,
                    status=PurchaseStatus.FAILED,
                    completed_at=datetime.now(),
                    error_message=str(e)
                )
            raise
            
        except Exception as e:
            logger.exception(f"Unexpected TON purchase error: {e}")
            
            if purchase_request:
                return PurchaseResult(
                    request=purchase_request,
                    transaction_hash=None,
                    status=PurchaseStatus.FAILED,
                    completed_at=datetime.now(),
                    error_message=f"Unexpected error: {str(e)}"
                )
            raise APIError(f"Unexpected error: {str(e)}")


class StarsPaymentStrategy(PaymentStrategy):
    """Telegram Stars payment strategy with advanced session management"""
    
    def __init__(self, api_client: StickerdomAPI, stars_payment: TelegramStarsPayment, cache_manager: Optional[StateCache] = None):
        super().__init__(api_client, cache_manager)
        self.stars_payment = stars_payment
        
        # Import session manager
        try:
            from services.stars_session_manager import get_stars_session_manager
            self.session_manager = get_stars_session_manager()
        except ImportError:
            self.session_manager = None
            logger.warning("Stars session manager not available, using basic strategy")
    
    def get_method_name(self) -> str:
        return "STARS"
    
    async def calculate_max_purchases(
        self,
        collection_id: int,
        character_id: int,
        stickers_per_purchase: int
    ) -> tuple[int, float]:
        """Calculate maximum Stars purchases with session management"""
        # Validate inputs
        self.validator.validate_purchase_params(collection_id, character_id, stickers_per_purchase)
        
        if self.session_manager:
            # Use session manager for intelligent calculation
            session_info = self.session_manager.get_session_info()
            
            # Calculate remaining purchases for this session
            remaining_in_session = settings.stars_max_purchases_per_session - session_info['purchases_this_session']
            
            # Adjust based on session quality
            quality_factor = session_info['quality_score']
            adjusted_max = int(remaining_in_session * quality_factor)
            
            max_purchases = max(0, min(adjusted_max, remaining_in_session))
            
            logger.info(f"💫 Stars purchases available: {max_purchases} (quality: {quality_factor:.2f})")
        else:
            # Fallback to basic calculation
            max_purchases = getattr(settings, 'stars_max_purchases_per_session', 3)
        
        return max_purchases, 0.0  # No cost calculation for Stars
    
    async def execute_purchase(
        self,
        collection_id: int,
        character_id: int,
        count: int
    ) -> PurchaseResult:
        """Execute Stars purchase with advanced session management"""
        purchase_request = None
        start_time = time.time()
        
        try:
            # Check session readiness
            if self.session_manager:
                can_purchase, reason = await self.session_manager.can_make_purchase()
                if not can_purchase:
                    raise APIError(f"Session not ready: {reason}")
                
                logger.info(f"💫 Stars purchase authorized: {reason}")
            
            # Input validation
            self.validator.validate_purchase_params(collection_id, character_id, count)
            
            # Validate collection and character availability
            collection = await self.api.get_collection(collection_id, priority=RequestPriority.HIGH)
            if not collection or not collection.is_active:
                raise CollectionNotAvailableError(f"Collection {collection_id} not available")

            character = next((c for c in collection.characters if c.id == character_id), None)
            if not character:
                raise CollectionNotAvailableError(f"Character {character_id} not found")
            
            # Validate and adjust count based on availability
            count = self.validator.validate_character_availability(character, count)
            
            # Get Stars invoice URL with configured timeout
            invoice_timeout = getattr(settings, 'stars_invoice_timeout', 30)
            character_stars_url = await asyncio.wait_for(
                self.api.get_character_stars_invoice_url(collection_id, character_id, count),
                timeout=invoice_timeout
            )
            
            if not character_stars_url:
                raise APIError("Failed to get Stars invoice URL")
            
            # Process Stars payment with configured timeout
            payment_timeout = getattr(settings, 'stars_payment_timeout', 120)
            payment_result = await asyncio.wait_for(
                self.stars_payment.pay_invoice(character_stars_url),
                timeout=payment_timeout
            )
            
            if not payment_result:
                raise APIError("Stars payment failed - no result returned")
            
            # Create purchase request for Stars
            purchase_request = PurchaseRequest(
                collection_id=collection_id,
                character_id=character_id,
                count=count,
                price_per_item=0,  # Stars price not tracked in TON
                total_amount=Decimal(0),
                order_id=payment_result,
                destination_wallet="",  # No wallet for Stars
                created_at=datetime.now()
            )

            result = PurchaseResult(
                request=purchase_request,
                transaction_hash=payment_result,
                status=PurchaseStatus.CONFIRMED,
                completed_at=datetime.now()
            )
            
            # Record successful purchase in session manager
            if self.session_manager:
                response_time = time.time() - start_time
                await self.session_manager.record_purchase_attempt(
                    success=True, 
                    response_time=response_time
                )
            
            logger.info(f"Stars purchase completed successfully: {payment_result}")
            return result
            
        except asyncio.TimeoutError:
            error_msg = "Stars purchase timed out"
            logger.error(error_msg)
            
            if purchase_request:
                return PurchaseResult(
                    request=purchase_request,
                    transaction_hash=None,
                    status=PurchaseStatus.TIMEOUT,
                    completed_at=datetime.now(),
                    error_message=error_msg
                )
            raise APIError(error_msg)
            
        except (APIError, CollectionNotAvailableError) as e:
            error_type = type(e).__name__
            logger.error(f"Stars purchase failed: {e}")
            
            # Record failed purchase in session manager
            if self.session_manager:
                response_time = time.time() - start_time
                await self.session_manager.record_purchase_attempt(
                    success=False, 
                    response_time=response_time,
                    error_type=error_type
                )
            
            if purchase_request:
                return PurchaseResult(
                    request=purchase_request,
                    transaction_hash=None,
                    status=PurchaseStatus.FAILED,
                    completed_at=datetime.now(),
                    error_message=str(e)
                )
            raise
            
        except Exception as e:
            error_type = type(e).__name__
            logger.exception(f"Unexpected Stars purchase error: {e}")
            
            # Record failed purchase in session manager
            if self.session_manager:
                response_time = time.time() - start_time
                await self.session_manager.record_purchase_attempt(
                    success=False, 
                    response_time=response_time,
                    error_type=error_type
                )
            
            if purchase_request:
                return PurchaseResult(
                    request=purchase_request,
                    transaction_hash=None,
                    status=PurchaseStatus.FAILED,
                    completed_at=datetime.now(),
                    error_message=f"Unexpected error: {str(e)}"
                )
            raise APIError(f"Unexpected error: {str(e)}") 