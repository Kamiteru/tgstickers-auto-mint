import asyncio
from datetime import datetime
from decimal import Decimal
from typing import List, Tuple, Optional

from services.api_client import StickerdomAPI
from services.ton_wallet import TONWalletManager
from services.telegram_stars import TelegramStarsPayment
from models import (
    PurchaseRequest, PurchaseResult, PurchaseStatus
)
from exceptions import (
    InsufficientBalanceError, CollectionNotAvailableError, APIError
)
from config import settings
from utils.logger import logger


class PurchaseOrchestrator:
    
    def __init__(self, api_client: StickerdomAPI, wallet_manager: Optional[TONWalletManager] = None, cache_manager: Optional['StateCache'] = None, stars_payment: Optional[TelegramStarsPayment] = None):
        self.api = api_client
        self.wallet = wallet_manager
        self.cache = cache_manager  # Optional cache for performance optimization
        self.stars_payment = stars_payment
    

    def calculate_max_purchases(
        self,
        available_balance: float,
        price_per_sticker: float,
        stickers_per_purchase: int = 5
    ) -> Tuple[int, float]:
        """Calculate maximum number of purchases possible with available balance"""
        cost_per_purchase = price_per_sticker * stickers_per_purchase
        cost_with_gas = cost_per_purchase + settings.gas_amount
        
        if cost_with_gas > available_balance:
            max_purchases = 0
        else:
            max_purchases = int(available_balance / cost_with_gas)
        
        total_cost = max_purchases * cost_per_purchase
        total_gas = max_purchases * settings.gas_amount
        
        logger.info(
            f"Balance: {available_balance:.2f} TON, "
            f"Can make {max_purchases} purchases "
            f"({max_purchases * stickers_per_purchase} stickers total), "
            f"Total cost: {total_cost:.2f} TON + {total_gas:.2f} TON gas"
        )
        
        return max_purchases, total_cost + total_gas
    

    async def execute_multiple_purchases(
        self,
        collection_id: int,
        character_id: int
    ) -> List[PurchaseResult]:
        """Execute multiple purchases using all available payment methods"""
        # Check if multiple payment methods are configured
        if len(settings.payment_methods) > 1:
            return await self.execute_parallel_payment_purchases(collection_id, character_id)
        else:
            return await self.execute_single_method_purchases(collection_id, character_id)

    async def execute_parallel_payment_purchases(
        self,
        collection_id: int,
        character_id: int
    ) -> List[PurchaseResult]:
        """Execute purchases using multiple payment methods simultaneously for maximum speed"""
        logger.info(f"Starting parallel purchases with methods: {', '.join(settings.payment_methods)}")
        
        # Create tasks for each payment method
        tasks = []
        if 'TON' in settings.payment_methods and self.wallet:
            tasks.append(self.execute_single_method_purchases(collection_id, character_id, force_method='TON'))
        if 'STARS' in settings.payment_methods and self.stars_payment:
            tasks.append(self.execute_single_method_purchases(collection_id, character_id, force_method='STARS'))
        
        if not tasks:
            raise CollectionNotAvailableError("No payment methods properly configured")
        
        # Run all payment methods in parallel
        all_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Combine results from all methods
        combined_results = []
        for result_group in all_results:
            if isinstance(result_group, Exception):
                logger.error(f"Payment method failed: {result_group}")
                continue
            combined_results.extend(result_group)
        
        # Log summary of parallel purchases
        successful = sum(1 for r in combined_results if r.is_successful)
        total_stickers = successful * settings.stickers_per_purchase
        
        method_summary = {}
        for result in combined_results:
            if result.is_successful and result.request:
                method = 'STARS' if result.request.total_amount == Decimal(0) else 'TON'
                method_summary[method] = method_summary.get(method, 0) + 1
        
        summary_parts = []
        for method, count in method_summary.items():
            summary_parts.append(f"{count} via {method}")
        
        logger.info(
            f"Parallel purchase session completed: "
            f"{successful} successful purchases ({total_stickers} stickers) - "
            f"{', '.join(summary_parts)}"
        )
        
        return combined_results

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
            collection = await self.api.get_collection(collection_id)
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
                f"Character: {character.name} (stock: {character.left}, price: {int(character.price)} stars per sticker)")

            # Calculate max purchases based on payment method
            if active_method == 'STARS':
                max_purchases = 3  # Conservative number for Stars
                logger.info(f"Using Telegram Stars payment - attempting {max_purchases} purchases")
            else:
                # TON payment logic
                if self.cache:
                    character_price_ton = await self.cache.get_cached_price(collection_id, character_id)
                else:
                    character_price_ton = await self.api.get_character_price(collection_id, character_id, "TON")
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
                    min_required = character_price_ton * settings.stickers_per_purchase + settings.gas_amount
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
        """Execute single purchase with validation"""
        count = count or settings.stickers_per_purchase
        purchase_request = None

        try:
            # Re-validate collection state (it might have changed)
            collection = await self.api.get_collection(collection_id)
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
                required = character_price_ton * count + settings.gas_amount

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
                    price_per_item=character_price_ton,
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
        