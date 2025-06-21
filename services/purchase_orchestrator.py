import asyncio
from datetime import datetime
from decimal import Decimal
from typing import List, Tuple, Optional, Dict, Any

from services.api_client import StickerdomAPI
from services.ton_wallet import TONWalletManager
from services.telegram_stars import TelegramStarsPayment
from services.cache_manager import StateCache
from services.payment_factory import PaymentMethodFactory
from services.payment_strategies import PaymentStrategy
from services.validators import PurchaseValidator, SecurityValidator
from services.rate_limiter import RequestPriority
from models import (
    PurchaseRequest, PurchaseResult, PurchaseStatus
)
from exceptions import (
    InsufficientBalanceError, CollectionNotAvailableError, APIError
)
from config import settings
from utils.logger import logger


class PurchaseOrchestrator:
    """
    Orchestrates purchase operations using payment strategies for improved separation of concerns.
    Handles validation, concurrency control, and error handling.
    """
    
    def __init__(
        self, 
        api_client: StickerdomAPI, 
        wallet_manager: Optional[TONWalletManager] = None, 
        cache_manager: Optional[StateCache] = None, 
        stars_payment: Optional[TelegramStarsPayment] = None
    ):
        self.api = api_client
        self.cache = cache_manager
        
        # Initialize validators
        self.validator = PurchaseValidator()
        self.security_validator = SecurityValidator()
        
        # Initialize payment factory and strategies
        self.payment_factory = PaymentMethodFactory(
            api_client=api_client,
            wallet_manager=wallet_manager,
            stars_payment=stars_payment,
            cache_manager=cache_manager
        )
        
        # Create payment strategies for all configured methods
        try:
            self.payment_strategies = self.payment_factory.create_all_strategies()
            available_methods = list(self.payment_strategies.keys())
            logger.info(f"Initialized payment strategies: {', '.join(available_methods)}")
        except Exception as e:
            logger.error(f"Failed to initialize payment strategies: {e}")
            self.payment_strategies = {}
        
        # Legacy compatibility
        self.wallet = wallet_manager
        self.stars_payment = stars_payment
    

    def calculate_max_purchases(
        self,
        available_balance: float,
        price_per_pack: float,
        stickers_per_purchase: int = 5
    ) -> Tuple[int, float]:
        """Calculate maximum number of purchases with enhanced validation"""
        try:
            # Use validator for safe calculation
            max_purchases, total_cost = self.validator.validate_max_purchases_calculation(
                available_balance,
                price_per_pack,
                stickers_per_purchase
            )
            
            logger.info(
                f"Balance: {available_balance:.6f} TON, "
                f"Can make {max_purchases} purchases "
                f"({max_purchases * stickers_per_purchase} stickers total), "
                f"Total cost: {total_cost:.6f} TON"
            )
            
            return max_purchases, total_cost
            
        except Exception as e:
            logger.error(f"Error calculating max purchases: {e}")
            return 0, 0.0
    

    async def execute_multiple_purchases(
        self,
        collection_id: int,
        character_id: int
    ) -> List[PurchaseResult]:
        """Execute multiple purchases using all available payment methods with enhanced validation"""
        try:
            # Input validation
            self.validator.validate_purchase_params(collection_id, character_id, settings.stickers_per_purchase)
            
            # Check available strategies
            if not self.payment_strategies:
                raise APIError("No payment strategies available")
            
            # Security validation
            await self.security_validator.validate_with_timeout(
                self.security_validator.validate_purchase_rate,
                30.0,  # 30 second timeout
                len(self.payment_strategies),  # Number of potential purchases
                60,  # Time window in minutes
                50   # Max purchases per window
            )
            
            # Execute based on number of available payment methods
            if len(self.payment_strategies) > 1:
                return await self.execute_parallel_payment_purchases(collection_id, character_id)
            else:
                return await self.execute_single_method_purchases(collection_id, character_id)
                
        except Exception as e:
            logger.error(f"Failed to execute multiple purchases: {e}")
            raise

    async def execute_parallel_payment_purchases(
        self,
        collection_id: int,
        character_id: int
    ) -> List[PurchaseResult]:
        """Execute purchases using multiple payment strategies simultaneously with improved error handling"""
        available_methods = list(self.payment_strategies.keys())
        logger.info(f"Starting parallel purchases with strategies: {', '.join(available_methods)}")
        
        try:
            # Create tasks for each payment strategy
            tasks = []
            for method_name, strategy in self.payment_strategies.items():
                task = self._execute_strategy_purchases(
                    strategy, 
                    collection_id, 
                    character_id, 
                    method_name
                )
                tasks.append(task)
            
            if not tasks:
                raise APIError("No payment strategies available for parallel execution")
            
            # Run all payment methods in parallel with timeout
            all_results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=300.0  # 5 minute timeout for all parallel operations
            )
            
            # Combine results from all strategies
            combined_results = []
            for result_group in all_results:
                if isinstance(result_group, Exception):
                    logger.error(f"Payment strategy failed: {result_group}")
                    continue
                if isinstance(result_group, list):
                    combined_results.extend(result_group)
                else:
                    combined_results.append(result_group)
            
            # Generate summary with improved method detection
            successful = sum(1 for r in combined_results if r.is_successful)
            total_stickers = successful * settings.stickers_per_purchase
            
            method_summary = {}
            for result in combined_results:
                if result.is_successful and result.request:
                    # Better method detection using request properties
                    if result.request.destination_wallet:
                        method = 'TON'
                    else:
                        method = 'STARS'
                    method_summary[method] = method_summary.get(method, 0) + 1
            
            summary_parts = [f"{count} via {method}" for method, count in method_summary.items()]
            
            logger.info(
                f"Parallel purchase session completed: "
                f"{successful} successful purchases ({total_stickers} stickers) - "
                f"{', '.join(summary_parts) if summary_parts else 'no successful purchases'}"
            )
            
            return combined_results
            
        except asyncio.TimeoutError:
            logger.error("Parallel purchases timed out after 5 minutes")
            raise APIError("Parallel purchases timed out")
        except Exception as e:
            logger.error(f"Parallel purchases failed: {e}")
            raise

    async def _execute_strategy_purchases(
        self,
        strategy: PaymentStrategy,
        collection_id: int,
        character_id: int,
        method_name: str
    ) -> List[PurchaseResult]:
        """Execute purchases using a specific payment strategy"""
        results = []
        
        try:
            # Calculate max purchases for this strategy
            max_purchases, total_cost = await strategy.calculate_max_purchases(
                collection_id,
                character_id,
                settings.stickers_per_purchase
            )
            
            if max_purchases == 0:
                logger.warning(f"No purchases possible with {method_name} strategy")
                return results
            
            logger.info(f"Starting {max_purchases} purchase(s) with {method_name} strategy...")
            
            # Execute purchases with this strategy
            for i in range(max_purchases):
                logger.info(f"Processing {method_name} purchase {i + 1}/{max_purchases}...")
                
                try:
                    result = await asyncio.wait_for(
                        strategy.execute_purchase(
                            collection_id,
                            character_id,
                            settings.stickers_per_purchase
                        ),
                        timeout=120.0  # 2 minute timeout per purchase
                    )
                    results.append(result)
                    
                    if result.is_successful:
                        logger.info(
                            f"{method_name} purchase {i + 1} completed! "
                            f"TX: {result.transaction_hash}"
                        )
                    else:
                        logger.error(f"{method_name} purchase {i + 1} failed: {result.error_message}")
                        # Stop on critical failures
                        if "insufficient" in result.error_message.lower():
                            logger.error("Stopping strategy due to insufficient funds")
                            break
                
                except asyncio.TimeoutError:
                    logger.error(f"{method_name} purchase {i + 1} timed out")
                    break
                except Exception as e:
                    logger.error(f"{method_name} purchase {i + 1} failed with exception: {e}")
                    break
                
                # Delay between purchases within same strategy
                if i < max_purchases - 1:
                    await asyncio.sleep(settings.purchase_delay)
            
            # Log strategy summary
            successful = sum(1 for r in results if r.is_successful)
            total_stickers = successful * settings.stickers_per_purchase
            
            logger.info(
                f"{method_name} strategy completed: "
                f"{successful}/{max_purchases} successful, "
                f"{total_stickers} stickers acquired"
            )
            
            return results
            
        except Exception as e:
            logger.error(f"{method_name} strategy execution failed: {e}")
            return results

    async def execute_single_method_purchases(
        self,
        collection_id: int,
        character_id: int,
        force_method: Optional[str] = None
    ) -> List[PurchaseResult]:
        """Execute multiple purchases with a single payment method"""
        results = []
        count = settings.stickers_per_purchase
        
        # Determine which method to use
        if force_method:
            active_method = force_method
        else:
            active_method = settings.payment_methods[0]

        try:
            # Validate collection availability
            collection = await self.api.get_collection(collection_id, priority=RequestPriority.HIGH)
            if not collection or not collection.is_active:
                raise CollectionNotAvailableError(f"Collection {collection_id} not available")

            # Find target character
            character = next((c for c in collection.characters if c.id == character_id), None)
            if not character or not character.is_available:
                raise CollectionNotAvailableError(f"Character {character_id} not available")

            # Adjust count based on available stock
            if character.left < count:
                logger.warning(
                    f"Not enough stock. Requested: {count}, available: {character.left}"
                )
                count = character.left

            if count <= 0:
                raise CollectionNotAvailableError("No stock available")

            logger.info(
                f"Character: {character.name} (stock: {character.left}, price: {int(character.price)} stars per pack)")

            # Calculate max purchases based on payment method
            if active_method == 'STARS':
                max_purchases = 3  # Conservative number for Stars
                logger.info(f"Using Telegram Stars payment - attempting {max_purchases} purchases")
            else:
                # TON payment logic
                if self.cache:
                    character_price_ton = await self.cache.get_cached_price(collection_id, character_id)
                else:
                    character_price_ton = await self.api.get_character_price(collection_id, character_id, "TON", priority=RequestPriority.CRITICAL)
                    if not character_price_ton:
                        raise CollectionNotAvailableError(f"Could not get TON price for character {character_id}")

                # Check wallet balance and calculate max purchases
                if self.cache:
                    wallet_info = await self.cache.get_cached_balance()
                else:
                    wallet_info = await self.wallet.get_wallet_info()
                max_purchases, total_required = self.calculate_max_purchases(
                    wallet_info.balance_ton,
                    character_price_ton,
                    settings.stickers_per_purchase
                )
                
                if max_purchases == 0:
                    min_required = character_price_ton + settings.gas_amount  # Price is already per pack
                    raise InsufficientBalanceError(
                        f"Insufficient balance. Need at least {min_required:.2f} TON, "
                        f"have {wallet_info.balance_ton:.2f} TON"
                    )
                
                # Limit by available stock
                max_possible_by_stock = character.left // settings.stickers_per_purchase
                if max_possible_by_stock < max_purchases:
                    logger.info(f"Limiting purchases to {max_possible_by_stock} due to stock availability")
                    max_purchases = max_possible_by_stock

            logger.info(f"Starting {max_purchases} purchase(s) with {active_method}...")

            # Execute purchases
            for i in range(max_purchases):
                logger.info(f"Processing {active_method} purchase {i + 1}/{max_purchases}...")

                try:
                    result = await self.execute_purchase(
                        collection_id,
                        character_id,
                        settings.stickers_per_purchase,
                        force_method=active_method
                    )
                    results.append(result)

                    if result.is_successful:
                        logger.info(
                            f"{active_method} purchase {i + 1} completed! "
                            f"Order: {result.request.order_id}, "
                            f"TX: {result.transaction_hash}"
                        )
                    else:
                        logger.error(f"{active_method} purchase {i + 1} failed: {result.error_message}")
                        # For critical failures, stop the session
                        if "insufficient" in result.error_message.lower():
                            logger.error("Stopping due to insufficient funds")
                            break

                except Exception as e:
                    logger.error(f"{active_method} purchase {i + 1} failed with exception: {e}")
                    # Create failure result for tracking
                    failed_result = PurchaseResult(
                        request=None,
                        transaction_hash=None,
                        status=PurchaseStatus.FAILED,
                        completed_at=datetime.now(),
                        error_message=str(e)
                    )
                    results.append(failed_result)
                    break

                # Delay between purchases
                if i < max_purchases - 1:
                    await asyncio.sleep(settings.purchase_delay)

            # Summary
            successful = sum(1 for r in results if r.is_successful)
            total_stickers = successful * settings.stickers_per_purchase
            
            if active_method == 'STARS':
                logger.info(
                    f"{active_method} purchase session completed: "
                    f"{successful}/{max_purchases} successful, "
                    f"{total_stickers} stickers bought with Telegram Stars"
                )
            else:
                total_spent = sum(
                    float(r.request.total_amount_ton)
                    for r in results
                    if r.is_successful and r.request
                )
                logger.info(
                    f"{active_method} purchase session completed: "
                    f"{successful}/{max_purchases} successful, "
                    f"{total_stickers} stickers bought, "
                    f"{total_spent:.2f} TON spent"
                )

            return results

        except Exception as e:
            logger.error(f"{active_method} purchase session failed: {e}")
            raise

    async def execute_purchase(
        self,
        collection_id: int,
        character_id: int,
        count: int = None,
        force_method: Optional[str] = None
    ) -> PurchaseResult:
        """Execute single purchase using payment strategies with enhanced validation"""
        count = count or settings.stickers_per_purchase
        
        try:
            # Input validation
            self.validator.validate_purchase_params(collection_id, character_id, count)
            
            # Determine payment method
            payment_method = force_method or settings.payment_methods[0]
            payment_method = self.validator.validate_payment_method(payment_method)
            
            # Get appropriate strategy
            if payment_method not in self.payment_strategies:
                raise APIError(f"Payment strategy for {payment_method} not available")
            
            strategy = self.payment_strategies[payment_method]
            
            # Execute purchase using strategy with timeout
            result = await asyncio.wait_for(
                strategy.execute_purchase(collection_id, character_id, count),
                timeout=120.0  # 2 minute timeout
            )
            
            logger.info(f"Purchase completed via {payment_method}: {result.transaction_hash}")
            return result
            
        except asyncio.TimeoutError:
            error_msg = f"Purchase timed out after 2 minutes"
            logger.error(error_msg)
            raise APIError(error_msg)
            
        except (APIError, CollectionNotAvailableError, InsufficientBalanceError) as e:
            logger.error(f"Purchase failed: {e}")
            raise
            
        except Exception as e:
            logger.exception(f"Unexpected purchase error: {e}")
            raise APIError(f"Unexpected error: {str(e)}")

    # Legacy execute_purchase method for backward compatibility
    async def _legacy_execute_purchase(
        self,
        collection_id: int,
        character_id: int,
        count: int = None,
        force_method: Optional[str] = None
    ) -> PurchaseResult:
        """Legacy execute purchase method - kept for backward compatibility"""
        count = count or settings.stickers_per_purchase
        purchase_request = None

        try:
            # Validate collection availability
            collection = await self.api.get_collection(collection_id, priority=RequestPriority.HIGH)
            if not collection or not collection.is_active:
                raise CollectionNotAvailableError(f"Collection {collection_id} not available")

            character = next((c for c in collection.characters if c.id == character_id), None)
            if not character or not character.is_available:
                raise CollectionNotAvailableError(f"Character {character_id} not available")

            # Adjust count based on available stock
            if character.left < count:
                logger.warning(
                    f"Not enough stock. Requested: {count}, available: {character.left}"
                )
                count = character.left

            if count <= 0:
                raise CollectionNotAvailableError("No stock available")

            # Determine payment method
            payment_method = force_method or settings.payment_methods[0]
            
            if payment_method == 'STARS':
                # Telegram Stars payment flow
                character_stars_url = await self.api.get_character_stars_invoice_url(collection_id, character_id, count)
                payment_result = await self.stars_payment.pay_invoice(character_stars_url)
                
                purchase_request = PurchaseRequest(
                    collection_id=collection_id,
                    character_id=character_id,
                    count=count,
                    price_per_item=0,  # Stars price not tracked in TON
                    total_amount=Decimal(0),
                    order_id=payment_result,
                    destination_wallet="",
                    created_at=datetime.now()
                )

                result = PurchaseResult(
                    request=purchase_request,
                    transaction_hash=payment_result,
                    status=PurchaseStatus.CONFIRMED,
                    completed_at=datetime.now()
                )

                return result
            else:
                # TON payment flow (existing logic)
                # Get fresh price (use cache if available for performance)
                if self.cache:
                    character_price_ton = await self.cache.get_cached_price(collection_id, character_id)
                else:
                    character_price_ton = await self.api.get_character_price(collection_id, character_id, "TON")
                    if not character_price_ton:
                        raise CollectionNotAvailableError(f"Could not get TON price for character {character_id}")

                # Check wallet balance (use cache if available)
                if self.cache:
                    wallet_info = await self.cache.get_cached_balance()
                else:
                    wallet_info = await self.wallet.get_wallet_info()
                required = character_price_ton + settings.gas_amount  # Price is already per pack, not per sticker

                if not wallet_info.has_sufficient_balance(required):
                    raise InsufficientBalanceError(
                        f"Need {required:.2f} TON, have {wallet_info.balance_ton:.2f} TON"
                    )

                # Initiate purchase
                purchase_data = await self.api.initiate_purchase(
                    collection_id, character_id, count
                )

                purchase_request = PurchaseRequest(
                    collection_id=collection_id,
                    character_id=character_id,
                    count=count,
                    price_per_item=character_price_ton / count,  # Convert pack price to per-sticker price
                    total_amount=Decimal(purchase_data['total_amount']),
                    order_id=purchase_data['order_id'],
                    destination_wallet=purchase_data['wallet'],
                    created_at=datetime.now()
                )

                # Send payment
                tx_hash, completed_at = await self.wallet.send_payment(
                    destination=purchase_request.destination_wallet,
                    amount_nano=int(purchase_request.total_amount),
                    comment=purchase_request.order_id
                )

                result = PurchaseResult(
                    request=purchase_request,
                    transaction_hash=tx_hash,
                    status=PurchaseStatus.CONFIRMED,
                    completed_at=completed_at
                )

                logger.info(f"Purchase completed: {tx_hash}")
                return result

        except (APIError, CollectionNotAvailableError, InsufficientBalanceError) as e:
            logger.error(f"Purchase failed: {e}")

            if purchase_request:
                return PurchaseResult(
                    request=purchase_request,
                    transaction_hash=None,
                    status=PurchaseStatus.FAILED,
                    completed_at=datetime.now(),
                    error_message=str(e)
                )
            else:
                # Re-raise for higher level handling
                raise
        except Exception as e:
            logger.exception(f"Unexpected purchase error: {e}")

            if purchase_request:
                return PurchaseResult(
                    request=purchase_request,
                    transaction_hash=None,
                    status=PurchaseStatus.FAILED,
                    completed_at=datetime.now(),
                    error_message=f"Unexpected error: {str(e)}"
                )
            raise

    def get_available_payment_methods(self) -> list[str]:
        """Get list of available payment methods"""
        return list(self.payment_strategies.keys())
    
    def is_payment_method_available(self, method: str) -> bool:
        """Check if specific payment method is available"""
        return method in self.payment_strategies
    
    async def get_purchase_capabilities(self, collection_id: int, character_id: int) -> Dict[str, Dict]:
        """Get purchase capabilities for each available payment method"""
        capabilities = {}
        
        for method_name, strategy in self.payment_strategies.items():
            try:
                max_purchases, total_cost = await strategy.calculate_max_purchases(
                    collection_id,
                    character_id,
                    settings.stickers_per_purchase
                )
                
                capabilities[method_name] = {
                    "max_purchases": max_purchases,
                    "total_cost": total_cost,
                    "max_stickers": max_purchases * settings.stickers_per_purchase,
                    "available": max_purchases > 0
                }
                
            except Exception as e:
                logger.error(f"Failed to get capabilities for {method_name}: {e}")
                capabilities[method_name] = {
                    "max_purchases": 0,
                    "total_cost": 0.0,
                    "max_stickers": 0,
                    "available": False,
                    "error": str(e)
                }
        
        return capabilities
    
    def get_orchestrator_status(self) -> Dict[str, Any]:
        """Get orchestrator status and configuration"""
        return {
            "available_strategies": list(self.payment_strategies.keys()),
            "configured_methods": settings.payment_methods,
            "cache_enabled": self.cache is not None,
            "validator_enabled": True,  # Always enabled in new implementation
            "legacy_mode": False  # Using new strategy-based implementation
        }
        