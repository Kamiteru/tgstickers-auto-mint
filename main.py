import asyncio
import signal
import argparse

from services import StickerdomAPI, TONWalletManager, PurchaseOrchestrator, StateCache, TelegramStarsPayment, CaptchaManager, get_token, threaded_purchase_manager
from monitoring import CollectionWatcher
from models import CollectionInfo
from utils.logger import logger
from config import settings
from exceptions import ConfigError


class StickerHunterBot:
    
    def __init__(self):
        # Initialize CAPTCHA manager first
        self.captcha_manager = CaptchaManager() if settings.captcha_enabled else None
        self.api = StickerdomAPI(self.captcha_manager)
        self.wallet = TONWalletManager() if 'TON' in settings.payment_methods else None
        self.stars_payment = TelegramStarsPayment() if 'STARS' in settings.payment_methods else None
        self.cache = StateCache(self.api, self.wallet) if self.wallet else None  # Performance cache
        self.orchestrator = PurchaseOrchestrator(self.api, self.wallet, self.cache, self.stars_payment)
        self.watcher = CollectionWatcher(self.api)
        self._running = False
        self._purchase_in_progress = False
    

    async def initialize(self):
        """Initialize bot with configuration validation"""
        logger.info("Initializing Sticker Hunter Bot...")
        
        # Validate configuration first
        try:
            settings.validate()
        except ConfigError as e:
            logger.error(f"Configuration error: {e}")
            raise
        
        # Test API connection
        if not await self.api.test_connection():
            raise RuntimeError("Failed to connect to Stickerdom API")
        
        # Initialize payment methods
        logger.info(f"Payment methods: {', '.join(settings.payment_methods)}")
        
        if 'TON' in settings.payment_methods:
            await self.wallet.initialize()
            wallet_info = await self.wallet.get_wallet_info()
            
            logger.info(f"TON Wallet: {wallet_info.address}")
            logger.info(f"TON Balance: {wallet_info.balance_ton:.9f} TON")
            
            if wallet_info.balance_ton < 0.1:  # Minimum reasonable balance
                logger.warning(f"Low wallet balance: {wallet_info.balance_ton:.9f} TON")
        
        if 'STARS' in settings.payment_methods:
            logger.info("Initializing Telegram Stars payment...")
            if not self.stars_payment.check_bot_connection():
                raise RuntimeError("Failed to connect to Telegram for Stars payments")
            logger.info("Telegram Stars connection verified")
        
        # JWT token will be refreshed automatically on first API request if needed
        
        logger.info("Bot initialized successfully!")
    

    async def run(self, collection_id: int, character_id: int, continuous: bool = False):
        """Main bot execution loop"""
        self._running = True
        
        try:
            await self.initialize()
            
            logger.info(f"🔍 Checking collection {collection_id}...")
            collection = await self.api.get_collection(collection_id)
            
            if collection is None:
                logger.info(
                    f"⏳ Collection {collection_id} not found. "
                    f"This is normal for upcoming drops. "
                    f"Bot will wait for it to appear..."
                )
            else:
                logger.info(
                    f"✅ Found collection: {collection.name} "
                    f"(Status: {collection.status}, Total: {collection.total_count})"
                )
            
            # Preload cache for performance optimization - get balance and price beforehand
            logger.info("🚀 Preloading cache for optimal purchase performance...")
            try:
                await self.cache.preload_data(collection_id, character_id)
                logger.info("✅ Cache preloaded successfully")
            except Exception as e:
                logger.warning(f"Cache preload failed: {e}. Will use direct API calls.")
            
            # Start monitoring
            await self.watcher.watch_collection(
                collection_id,
                character_id,
                lambda col, char_id: asyncio.create_task(
                    self._on_collection_available(col, char_id, continuous)
                )
            )
            
            logger.info(f"👀 Monitoring collection {collection_id}, character {character_id}...")
            if continuous:
                logger.info("♾️  Continuous mode: Will keep buying while balance and stock available")
            
            # Notifications disabled
            
            # Main loop
            while self._running:
                await asyncio.sleep(1)
                
        except KeyboardInterrupt:
            logger.info("Received stop signal")
        except Exception as e:
            logger.error(f"Bot error: {e}")
            raise
        finally:
            await self.shutdown()
    

    async def _on_collection_available(self, collection: CollectionInfo, character_id: int, continuous: bool):
        """Handle collection availability event"""
        if self._purchase_in_progress:
            logger.info("Purchase already in progress, skipping...")
            return
        
        self._purchase_in_progress = True
        
        try:
            logger.info(f"🚀 Collection {collection.name} is available for purchase!")
            
            results = await self.orchestrator.execute_multiple_purchases(collection.id, character_id)
            
            successful_count = sum(1 for r in results if r.is_successful)
            failed_count = len(results) - successful_count
            
            if successful_count > 0:
                # Find character to get stickers count
                character = next((c for c in collection.characters if c.id == character_id), None)
                stickers_per_pack = character.stickers_count if character else 1
                total_stickers = successful_count * stickers_per_pack
                logger.info(f"✅ Successfully completed {successful_count} purchases ({total_stickers} stickers)!")
                
                if failed_count > 0:
                    logger.warning(f"⚠️  {failed_count} purchases failed")
                
                # Calculate total cost and determine currency for notification
                total_cost_ton = sum(
                    float(r.request.total_amount_ton) 
                    for r in results 
                    if r.is_successful and r.request and r.request.total_amount > 0
                )
                
                total_cost_stars = sum(
                    r.request.count * int(character.price if character else 0)
                    for r in results 
                    if r.is_successful and r.request and r.request.total_amount == 0
                )
                
                # Find character name for notification
                character = next((c for c in collection.characters if c.id == character_id), None)
                character_name = character.name if character else f"Character {character_id}"
                
                # Purchase completed successfully
                
                if not continuous:
                    logger.info("Single purchase mode: stopping monitoring")
                    self.watcher.stop_watching(collection.id)
                    self._running = False
                else:
                    if 'TON' in settings.payment_methods and self.wallet:
                        wallet_info = await self.wallet.get_wallet_info()
                        logger.info(
                            f"Continuous mode: Remaining balance {wallet_info.balance_ton:.2f} TON. "
                            f"Will continue monitoring..."
                        )
                    if 'STARS' in settings.payment_methods:
                        logger.info("Continuous mode: Will continue monitoring for Stars payments...")
            else:
                failed_count = len(results)
                if failed_count > 0:
                    logger.error(f"❌ All {failed_count} purchase attempts failed")
                    
                    # Get last error for logging
                    last_error = None
                    for r in reversed(results):
                        if r.error_message:
                            last_error = r.error_message
                            break
                    
                    if last_error:
                        logger.error(f"Last error: {last_error}")
                    
                    # Purchase failed
                    
                else:
                    logger.warning("⚠️ No purchase results returned")
                
        except Exception as e:
            logger.error(f"Failed to purchase: {e}")
        finally:
            self._purchase_in_progress = False
    

    async def shutdown(self):
        """Clean shutdown"""
        logger.info("Shutting down bot...")
        self._running = False
        await self.watcher.stop_all()
        if self.cache:
            await self.cache.stop_background_updates()  # Stop cache updates
        # JWT manager cleanup - no auto-refresh to stop
        if self.wallet:
            await self.wallet.close()
        if self.stars_payment:
            await self.stars_payment.close_session()
        logger.info("Bot shutdown complete")
    
    def stop(self):
        """Stop the bot"""
        self._running = False

    async def test_mode(self, collection_id: int, character_id: int):
        """Test mode: verify configuration and connections without purchases"""
        logger.info("🧪 Running in TEST MODE - no purchases will be made")
        
        try:
            await self.initialize()
            
            logger.info("1️⃣ Testing configuration...")
            logger.info("✅ Configuration is valid")
            
            logger.info("2️⃣ Testing API connection...")
            is_connected = await self.api.test_connection()
            if is_connected:
                logger.info("✅ API connection successful")
            else:
                raise Exception("API connection failed")
            
            logger.info("3️⃣ Testing TON wallet...")
            if 'TON' in settings.payment_methods and self.wallet:
                wallet_info = await self.wallet.get_wallet_info()
                logger.info(f"✅ Wallet connected: {wallet_info.address}")
                logger.info(f"💰 Balance: {wallet_info.balance_ton:.9f} TON")
            else:
                logger.info("ℹ️ TON wallet not configured")
            
            logger.info("3️⃣ Testing Telegram Stars client...")
            if 'STARS' in settings.payment_methods and self.stars_payment:
                # TelegramStarsPayment doesn't have test_connection method
                # Just check if it's initialized properly
                logger.info("✅ Telegram client connected for Stars payments")
            else:
                logger.info("ℹ️ Telegram Stars not configured")
                
            logger.info("5️⃣ Testing CAPTCHA system...")
            if self.captcha_manager:
                logger.info("✅ CAPTCHA system initialized")
            else:
                logger.info("ℹ️ CAPTCHA system disabled")
            
            # Test collection API
            logger.info("6️⃣ Testing collection API...")
            collection = await self.api.get_collection(collection_id)
            if collection:
                logger.info(f"✅ Collection found: {collection.name}")
                logger.info(f"📊 Status: {collection.status}")
                logger.info(f"📈 Total/Sold: {collection.total_count}/{collection.sold_count}")
                
                character = next((c for c in collection.characters if c.id == character_id), None)
                if character:
                    logger.info(f"✅ Character found: {character.name}")
                    logger.info(f"📦 Stock: {character.left}")
                    
                    # character.price is already in stars (Telegram's internal currency)
                    logger.info(f"💵 Price: {int(character.price)} stars per sticker")
                else:
                    logger.warning(f"⚠️ Character {character_id} not found in collection")
            else:
                logger.info(f"ℹ️ Collection {collection_id} not found (normal for upcoming drops)")
            
            logger.info("🎉 All tests completed successfully!")
            
        except Exception as e:
            logger.error(f"❌ Test failed: {e}")
            raise

    async def dry_run_mode(self, collection_id: int, character_id: int):
        """Dry run mode: simulate the full purchase process without transactions"""
        logger.info("🎭 Running in DRY RUN MODE - simulating purchases")
        
        try:
            await self.initialize()
            
            collection = await self.api.get_collection(collection_id)
            if not collection:
                logger.info(f"⏳ Collection {collection_id} not found. Would wait for it to appear...")
                # Notifications disabled - would start monitoring
                return
            
            character = next((c for c in collection.characters if c.id == character_id), None)
            if not character:
                logger.error(f"❌ Character {character_id} not found")
                return
                
            if not character.is_available:
                logger.info(f"⏳ Character {character.name} not available (stock: {character.left})")
                return
            
            logger.info(f"🎯 Found available character: {character.name}")
            logger.info(f"📦 Stock: {character.left}")
            # Display price in stars (character.price is already in Telegram's internal currency)
            logger.info(f"💵 Price: {int(character.price)} stars per sticker")
            
            max_purchases_ton = 0
            max_purchases_stars = 0
            total_cost = 0
            
            if 'TON' in settings.payment_methods and self.wallet:
                # Get TON price for calculations
                character_price_ton = await self.api.get_character_price(collection_id, character_id, "TON")
                
                if character_price_ton:
                    logger.info(f"💰 Current TON price: {character_price_ton} TON per sticker")
                
                # Simulate purchase calculation
                wallet_info = await self.wallet.get_wallet_info()
                max_purchases_ton, total_cost = self.orchestrator.calculate_max_purchases(
                    wallet_info.balance_ton,
                    character_price_ton or character.price  # Price is already per pack
                )
            
            if 'STARS' in settings.payment_methods:
                logger.info("💫 Stars payment mode - no balance check needed")
                max_purchases_stars = 3  # Conservative number for Stars
            
            max_purchases = max_purchases_ton + max_purchases_stars
            
            if max_purchases > 0:
                # Get real stickers count for this character
                stickers_per_pack = character.stickers_count if character else 1
                total_stickers = max_purchases * stickers_per_pack
                purchase_details = []
                
                if max_purchases_ton > 0:
                    ton_stickers = max_purchases_ton * stickers_per_pack
                    purchase_details.append(f"{max_purchases_ton} orders via TON ({ton_stickers} stickers)")
                
                if max_purchases_stars > 0:
                    stars_stickers = max_purchases_stars * stickers_per_pack
                    purchase_details.append(f"{max_purchases_stars} orders via Stars ({stars_stickers} stickers)")
                
                logger.info(f"✅ SIMULATION: Would buy {max_purchases} total orders ({total_stickers} stickers)")
                logger.info(f"📊 Breakdown: {', '.join(purchase_details)}")
                
                if max_purchases_ton > 0:
                    logger.info(f"💰 SIMULATION: Would spend ~{total_cost:.2f} TON")
                
            else:
                if 'TON' in settings.payment_methods and self.wallet:
                    character_price_ton = await self.api.get_character_price(collection_id, character_id, "TON")
                    required = (character_price_ton or character.price) + settings.gas_amount  # Price is already per pack
                    wallet_info = await self.wallet.get_wallet_info()
                    logger.info(f"❌ SIMULATION: Insufficient TON balance")
                    logger.info(f"💸 Would need: {required:.2f} TON, have: {wallet_info.balance_ton:.2f} TON")
                
                if 'STARS' in settings.payment_methods:
                    logger.info(f"✅ Stars payment - ready to purchase when available")
            
            logger.info("🎭 Dry run completed successfully!")
            
        except Exception as e:
            logger.error(f"❌ Dry run failed: {e}")
            raise

    async def session_info_mode(self):
        """Show Telegram session information"""
        logger.info("📱 Getting Telegram session information...")
        
        if not self.stars_payment:
            logger.error("❌ Stars payment not configured")
            return
        
        try:
            session_info = await self.stars_payment.get_session_info()
            if session_info:
                logger.info("✅ Telegram Session Information:")
                logger.info(f"👤 User: {session_info['first_name']} (@{session_info.get('username', 'no_username')})")
                logger.info(f"📱 Phone: {session_info['phone']}")
                logger.info(f"🆔 User ID: {session_info['user_id']}")
                logger.info(f"⭐ Premium: {'Yes' if session_info['is_premium'] else 'No'}")
                logger.info(f"📁 Session file: {session_info['session_file']}")
                logger.info(f"💾 Session exists: {'Yes' if session_info['session_exists'] else 'No'}")
            else:
                logger.error("❌ Failed to get session information")
        except Exception as e:
            logger.error(f"❌ Error getting session info: {e}")

    async def logout_session_mode(self):
        """Logout from Telegram and clear session"""
        logger.info("🚪 Logging out from Telegram session...")
        
        if not self.stars_payment:
            logger.error("❌ Stars payment not configured")
            return
        
        try:
            await self.stars_payment.logout_session()
            logger.info("✅ Successfully logged out from Telegram")
            logger.info("⚠️ You will need to re-authenticate on next Stars payment")
        except Exception as e:
            logger.error(f"❌ Error during logout: {e}")

    async def clear_session_mode(self):
        """Clear local session files without logout"""
        logger.info("🗑️ Clearing local session files...")
        
        if not self.stars_payment:
            logger.error("❌ Stars payment not configured")
            return
        
        try:
            await self.stars_payment.clear_session_files()
            logger.info("✅ Session files cleared")
            logger.info("⚠️ You will need to re-authenticate on next Stars payment")
        except Exception as e:
            logger.error(f"❌ Error clearing session files: {e}")

    async def get_token_mode(self):
        """Get initial JWT token via browser automation"""
        logger.info("🔑 Getting initial JWT token via browser automation...")
        
        try:
            token = await get_token()
            if token:
                logger.info("✅ JWT token obtained successfully!")
                logger.info(f"Token: {token[:50]}...")
                logger.info("Please save this token to your config.py JWT_TOKEN setting")
                logger.info("You can now run the bot normally")
            else:
                logger.error("❌ Failed to obtain JWT token")
                logger.info("Please try again or set the token manually in config.py")
                
        except Exception as e:
            logger.error(f"❌ Error obtaining token: {e}")

    async def spam_mode(self, collection_id: int, character_id: int, attempts: int = 50):
        """Spam mode: multiple purchase attempts with different proxies"""
        logger.info(f"🔥 Starting SPAM mode: {attempts} attempts on collection {collection_id}")
        
        # Result tracking
        successful_results = []
        failed_results = []
        
        async def result_handler(result):
            """Handle worker results"""
            if result.success:
                successful_results.append(result)
                logger.info(
                    f"✅ SUCCESS #{len(successful_results)}: Worker {result.worker_id} "
                    f"bought {result.stickers_bought} stickers via {result.proxy_used}"
                )
            else:
                failed_results.append(result)
                logger.warning(
                    f"❌ FAILED #{len(failed_results)}: Worker {result.worker_id} "
                    f"error: {result.error}"
                )
        
        try:
            # Initialize bot first
            await self.initialize()
            
            # Initialize threaded purchase manager
            threaded_purchase_manager.set_result_callback(result_handler)
            await threaded_purchase_manager.initialize()
            await threaded_purchase_manager.start()
            
            # Start spam
            await threaded_purchase_manager.spam_collection(
                collection_id, 
                character_id, 
                total_attempts=attempts,
                delay_between_attempts=0.05  # 50ms delay between task additions
            )
            
            # Wait for completion with timeout
            logger.info("⏳ Waiting for all purchase attempts to complete...")
            await threaded_purchase_manager.wait_for_completion(timeout=300)  # 5 minutes timeout
            
            # Report results
            total_stickers = sum(r.stickers_bought for r in successful_results)
            success_rate = len(successful_results) / attempts * 100 if attempts > 0 else 0
            
            logger.info("🎯 SPAM MODE RESULTS:")
            logger.info(f"✅ Successful purchases: {len(successful_results)}")
            logger.info(f"❌ Failed purchases: {len(failed_results)}")
            logger.info(f"📦 Total stickers bought: {total_stickers}")
            logger.info(f"📊 Success rate: {success_rate:.1f}%")
            
            # Show proxy performance
            proxy_stats = {}
            for result in successful_results + failed_results:
                proxy = result.proxy_used or 'direct'
                if proxy not in proxy_stats:
                    proxy_stats[proxy] = {'success': 0, 'failed': 0}
                
                if result.success:
                    proxy_stats[proxy]['success'] += 1
                else:
                    proxy_stats[proxy]['failed'] += 1
            
            logger.info("🌐 Proxy performance:")
            for proxy, stats in proxy_stats.items():
                total = stats['success'] + stats['failed']
                rate = stats['success'] / total * 100 if total > 0 else 0
                logger.info(f"  {proxy}: {stats['success']}/{total} ({rate:.1f}%)")
            
        except Exception as e:
            logger.error(f"❌ Spam mode failed: {e}")
            raise
        finally:
            await threaded_purchase_manager.stop()


def parse_collection_character(arg: str) -> tuple[int, int]:
    """Parse collection/character format: character_id/collection_id"""
    try:
        parts = arg.split('/')
        if len(parts) != 2:
            raise ValueError("Invalid format")
            
        character_id, collection_id = int(parts[0]), int(parts[1])
        
        if character_id <= 0 or collection_id <= 0:
            raise ValueError("IDs must be positive")
            
        return collection_id, character_id
    except (ValueError, IndexError):
        raise ValueError(f"Invalid format '{arg}'. Use: character_id/collection_id (e.g., 2/15)")


async def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Sticker Hunter Bot - Automated Telegram sticker purchasing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py 2/19                    # Monitor collection 19, character 2
  python main.py 2/19 --once             # Buy once with current balance and exit
  python main.py 2/19 --continuous       # Keep buying while balance available
  python main.py 2/19 --test             # Test configuration and connections
  python main.py 2/19 --dry-run          # Simulate purchases without spending money
  python main.py 2/19 --session-info     # Show Telegram session information
  python main.py 2/19 --logout-session   # Logout from Telegram and clear session
  python main.py 2/19 --clear-session    # Clear local session files only
  python main.py 2/19 --spam --attempts 100 # Spam 100 purchase attempts with multiple workers
        """
    )
    parser.add_argument(
        "target",
        help="Character and collection in format: character_id/collection_id (e.g., 2/19)"
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Purchase once and exit (buys maximum possible with current balance)"
    )
    parser.add_argument(
        "--continuous",
        action="store_true",
        help="Continue monitoring and buying after successful purchases"
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Test mode: check configuration, API connection, wallet balance (no purchases)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Dry run: simulate purchases without actual transactions"
    )
    parser.add_argument(
        "--session-info",
        action="store_true",
        help="Show Telegram session information"
    )
    parser.add_argument(
        "--logout-session",
        action="store_true",
        help="Logout from Telegram and clear session files"
    )
    parser.add_argument(
        "--clear-session",
        action="store_true",
        help="Clear local session files without logout"
    )
    parser.add_argument(
        "--spam",
        action="store_true",
        help="Spam mode: multiple purchase attempts with different proxies"
    )
    parser.add_argument(
        "--attempts",
        type=int,
        default=50,
        help="Number of purchase attempts for spam mode (default: 50)"
    )
    
    args = parser.parse_args()
    
    # Validate arguments
    exclusive_args = [args.once, args.continuous, args.test, args.dry_run, args.session_info, 
                     args.logout_session, args.clear_session, args.spam]
    if sum(exclusive_args) > 1:
        logger.error("Cannot use multiple exclusive arguments together")
        return
    
    try:
        collection_id, character_id = parse_collection_character(args.target)
    except ValueError as e:
        logger.error(f"Error: {e}")
        return
    
    bot = StickerHunterBot()
    
    # Setup signal handlers
    def signal_handler(sig, frame):
        logger.info("Received shutdown signal")
        bot.stop()
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        if args.test:
            # Test mode - check everything without purchases
            await bot.test_mode(collection_id, character_id)
        elif args.dry_run:
            # Dry run mode - simulate purchases
            await bot.dry_run_mode(collection_id, character_id)
        elif args.session_info:
            # Show Telegram session info
            await bot.session_info_mode()
        elif args.logout_session:
            # Logout from Telegram
            await bot.logout_session_mode()
        elif args.clear_session:
            # Clear session files
            await bot.clear_session_mode()
        elif args.spam:
            # Spam mode - multiple purchase attempts
            await bot.spam_mode(collection_id, character_id, attempts=args.attempts)
        elif args.once:
            # One-time purchase mode
            await bot.initialize()
            
            try:
                results = await bot.orchestrator.execute_multiple_purchases(collection_id, character_id)
                successful = sum(1 for r in results if r.is_successful)
                
                if successful > 0:
                    # Get collection to find character stickers count
                    collection = await bot.api.get_collection(collection_id)
                    character = next((c for c in collection.characters if c.id == character_id), None) if collection else None
                    stickers_per_pack = character.stickers_count if character else 1
                    total_stickers = successful * stickers_per_pack
                    logger.info(f"✅ Purchase session successful! "
                              f"Completed {successful} purchases ({total_stickers} stickers)")
                else:
                    logger.error("❌ All purchase attempts failed")
            except Exception as e:
                logger.error(f"Purchase failed: {e}")
                    
            await bot.shutdown()
        else:
            # Monitoring mode (default or continuous)
            await bot.run(collection_id, character_id, continuous=args.continuous)
            
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except ConfigError as e:
        logger.error(f"Configuration error: {e}")
        logger.info("Please check your environment variables")
    except Exception as e:
        logger.error(f"Bot crashed: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
    