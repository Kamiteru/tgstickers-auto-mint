import asyncio
from decimal import Decimal
from typing import Optional

from exceptions import (
    InsufficientBalanceError, CollectionNotAvailableError, APIError,
    ValidationError, SecurityError, PurchaseTimeoutError
)
from config import settings
from utils.logger import logger


class PurchaseValidator:
    """Validator for purchase operations with comprehensive input validation"""
    
    @staticmethod
    def validate_purchase_params(collection_id: int, character_id: int, count: int) -> None:
        """Validate basic purchase parameters"""
        if collection_id <= 0:
            raise ValidationError(f"Invalid collection_id: {collection_id}. Must be positive")
        
        if character_id <= 0:
            raise ValidationError(f"Invalid character_id: {character_id}. Must be positive")
        
        if count <= 0:
            raise ValidationError(f"Invalid count: {count}. Must be positive")
        
        # Check against reasonable limits
        if count > 100:  # Reasonable upper limit
            raise ValidationError(f"Count too high: {count}. Maximum allowed is 100")
    
    @staticmethod
    def validate_balance_calculation(balance: float, required: float, gas_amount: float = None) -> None:
        """Validate balance vs required amount with proper error handling"""
        if balance < 0:
            raise InsufficientBalanceError(f"Invalid balance: {balance}. Cannot be negative")
        
        if required <= 0:
            raise ValidationError(f"Invalid required amount: {required}. Must be positive")
        
        gas_amount = gas_amount or settings.gas_amount
        total_required = required + gas_amount
        
        if balance < total_required:
            raise InsufficientBalanceError(
                f"Insufficient balance. Need {total_required:.6f} TON "
                f"({required:.6f} + {gas_amount:.6f} gas), have {balance:.6f} TON"
            )
    
    @staticmethod
    def validate_price_data(price: Optional[float], collection_id: int, character_id: int) -> float:
        """Validate and return price data with proper error handling"""
        if price is None:
            raise CollectionNotAvailableError(
                f"Could not get price for character {character_id} in collection {collection_id}"
            )
        
        if price <= 0:
            raise ValidationError(f"Invalid price: {price}. Must be positive")
        
        # Check against reasonable limits (prevent overflow/underflow)
        if price > 1000:  # More than 1000 TON seems unreasonable
            raise ValidationError(f"Price too high: {price} TON. Maximum reasonable price is 1000 TON")
        
        return price
    
    @staticmethod
    def validate_payment_method(method: str) -> str:
        """Validate payment method"""
        valid_methods = ['TON', 'STARS']
        if method not in valid_methods:
            raise ValidationError(f"Invalid payment method: {method}. Must be one of: {', '.join(valid_methods)}")
        return method
    
    @staticmethod
    def validate_character_availability(character, count: int) -> int:
        """Validate character availability and adjust count if needed"""
        if not character:
            raise CollectionNotAvailableError("Character not found")
        
        if not character.is_available:
            raise CollectionNotAvailableError(f"Character {character.id} is not available")
        
        if character.left <= 0:
            raise CollectionNotAvailableError(f"Character {character.id} is out of stock")
        
        # Adjust count to available stock
        adjusted_count = min(count, character.left)
        if adjusted_count != count:
            logger.warning(f"Adjusted count from {count} to {adjusted_count} due to stock limits")
        
        return adjusted_count
    
    @staticmethod  
    def validate_max_purchases_calculation(
        balance: float, 
        price_per_pack: float, 
        stickers_per_purchase: int
    ) -> tuple[int, float]:
        """Validate and calculate maximum purchases with safety checks"""
        # Input validation
        if balance < 0:
            raise InsufficientBalanceError(f"Invalid balance: {balance}")
        
        if price_per_pack <= 0:
            raise ValidationError(f"Invalid price per pack: {price_per_pack}")
        
        if stickers_per_purchase <= 0:
            raise ValidationError(f"Invalid stickers per purchase: {stickers_per_purchase}")
        
        gas_amount = settings.gas_amount
        if gas_amount <= 0:
            raise ValidationError(f"Invalid gas amount in settings: {gas_amount}")
        
        cost_with_gas = price_per_pack + gas_amount
        
        # Prevent division by zero
        if cost_with_gas <= 0:
            raise ValidationError(f"Invalid total cost calculation: {cost_with_gas}")
        
        # Calculate max purchases
        if balance < cost_with_gas:
            max_purchases = 0
        else:
            max_purchases = int(balance / cost_with_gas)
        
        # Sanity check - prevent unreasonably high number of purchases
        if max_purchases > 1000:  # Reasonable upper limit
            logger.warning(f"Limiting max purchases from {max_purchases} to 1000 for safety")
            max_purchases = 1000
        
        total_cost = max_purchases * price_per_pack
        total_gas = max_purchases * gas_amount
        
        return max_purchases, total_cost + total_gas


class SecurityValidator:
    """Security-focused validator for purchase operations"""
    
    @staticmethod
    def validate_transaction_limits(amount: float, daily_limit: float = 100.0) -> None:
        """Validate transaction against security limits"""
        if amount > daily_limit:
            raise SecurityError(f"Transaction amount {amount} TON exceeds daily limit {daily_limit} TON")
    
    @staticmethod
    def validate_purchase_rate(purchases_count: int, time_window_minutes: int = 60, max_per_window: int = 50) -> None:
        """Validate purchase rate to prevent abuse"""
        if purchases_count > max_per_window:
            raise SecurityError(
                f"Too many purchases: {purchases_count} in {time_window_minutes} minutes. "
                f"Maximum allowed: {max_per_window}"
            )
    
    @staticmethod
    async def validate_with_timeout(
        validation_func, 
        timeout_seconds: float = 30.0, 
        *args, 
        **kwargs
    ):
        """Execute validation with timeout to prevent hanging"""
        try:
            if asyncio.iscoroutinefunction(validation_func):
                return await asyncio.wait_for(
                    validation_func(*args, **kwargs), 
                    timeout=timeout_seconds
                )
            else:
                return validation_func(*args, **kwargs)
        except asyncio.TimeoutError:
            raise PurchaseTimeoutError(f"Validation timed out after {timeout_seconds} seconds") 