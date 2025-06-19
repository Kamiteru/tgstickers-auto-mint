import asyncio
import signal
import argparse

from services import StickerdomAPI, TONWalletManager, PurchaseOrchestrator, StateCache, TelegramStarsPayment, CaptchaManager
from monitoring import CollectionWatcher
from models import CollectionInfo
from utils.logger import logger
from utils.notifications import notifier
from config import settings
from exceptions import ConfigError


class StickerHunterBot:
    
    def __init__(self):
        # Initialize CAPTCHA manager first
        self.captcha_manager = CaptchaManager(notifier) if settings.captcha_enabled else None
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
            
            # Send start notification
            await notifier.notify_bot_started(collection_id, character_id)
            
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
                total_stickers = successful_count * settings.stickers_per_purchase
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
                
                # Determine primary payment method and send appropriate notification
                if total_cost_stars > 0 and total_cost_ton > 0:
                    # Mixed payments - send combined notification
                    combined_text = f"💫 {total_cost_stars} Stars + 💰 {total_cost_ton:.2f} TON"
                    await notifier.notify_purchase_success(
                        collection.name,
                        character_name,
                        successful_count,
                        total_stickers,
                        total_cost_stars,  # Use stars as primary for display
                        "MIXED",
                        combined_cost_text=combined_text
                    )
                elif total_cost_stars > 0:
                    # Stars only
                    await notifier.notify_purchase_success(
                        collection.name,
                        character_name,
                        successful_count,
                        total_stickers,
                        total_cost_stars,
                        "STARS"
                    )
                else:
                    # TON only (existing logic)
                    await notifier.notify_purchase_success(
                        collection.name,
                        character_name,
                        successful_count,
                        total_stickers,
                        total_cost_ton,
                        "TON"
                    )
                
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
                logger.error("❌ All purchase attempts failed")
                
                # Send failure notification
                character = next((c for c in collection.characters if c.id == character_id), None)
                character_name = character.name if character else f"Character {character_id}"
                
                error_message = "All purchase attempts failed"
                if results:
                    last_error = next((r.error_message for r in reversed(results) if r.error_message), None)
                    if last_error:
                        error_message = last_error
                
                await notifier.notify_purchase_failed(
                    collection.name,
                    character_name,
                    error_message
                )
                
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
            # Test configuration
            logger.info("1️⃣ Testing configuration...")
            settings.validate()
            logger.info("✅ Configuration is valid")
            
            # Test API connection
            logger.info("2️⃣ Testing API connection...")
            if await self.api.test_connection():
                logger.info("✅ API connection successful")
            else:
                logger.error("❌ API connection failed")
                return
            
            # Test payment methods
            if 'TON' in settings.payment_methods:
                logger.info("3️⃣ Testing TON wallet...")
                await self.wallet.initialize()
                wallet_info = await self.wallet.get_wallet_info()
                logger.info(f"✅ Wallet connected: {wallet_info.address}")
                logger.info(f"💰 Balance: {wallet_info.balance_ton:.9f} TON")
            
            if 'STARS' in settings.payment_methods:
                logger.info("3️⃣ Testing Telegram Stars client...")
                if self.stars_payment.check_bot_connection():
                    logger.info("✅ Telegram client connected for Stars payments")
                else:
                    logger.error("❌ Failed to connect to Telegram client")
                    return
            
            # Test notifications
            logger.info("4️⃣ Testing notifications...")
            await notifier.send_message("🧪 <b>Test notification</b>\nBot testing is working!")
            if notifier.enabled:
                logger.info("✅ Telegram notifications working")
            else:
                logger.info("ℹ️ Telegram notifications disabled (not configured)")
            
            # Test CAPTCHA system
            if self.captcha_manager:
                logger.info("5️⃣ Testing CAPTCHA system...")
                
                # Test captcha detection
                test_captcha_response = {
                    "error": "captcha_required",
                    "captcha_type": "recaptcha",
                    "site_key": "test_key"
                }
                
                challenge = self.captcha_manager.detect_captcha(test_captcha_response)
                if challenge:
                    logger.info(f"✅ CAPTCHA detection working: {challenge.captcha_type}")
                else:
                    logger.warning("⚠️ CAPTCHA detection not working")
                
                # Check solvers
                if hasattr(settings, 'anticaptcha_api_key') and settings.anticaptcha_api_key:
                    logger.info("✅ Anti-captcha API key configured")
                else:
                    logger.info("ℹ️ Anti-captcha API key not configured")
                    
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
                # Simulate notification
                await notifier.send_message(
                    f"🧪 <b>DRY RUN</b>\n"
                    f"Would start monitoring collection {collection_id}, character {character_id}"
                )
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
                    character_price_ton or character.price,
                    settings.stickers_per_purchase
                )
            
            if 'STARS' in settings.payment_methods:
                logger.info("💫 Stars payment mode - no balance check needed")
                max_purchases_stars = 3  # Conservative number for Stars
            
            max_purchases = max_purchases_ton + max_purchases_stars
            
            if max_purchases > 0:
                total_stickers = max_purchases * settings.stickers_per_purchase
                purchase_details = []
                
                if max_purchases_ton > 0:
                    ton_stickers = max_purchases_ton * settings.stickers_per_purchase
                    purchase_details.append(f"{max_purchases_ton} orders via TON ({ton_stickers} stickers)")
                
                if max_purchases_stars > 0:
                    stars_stickers = max_purchases_stars * settings.stickers_per_purchase
                    purchase_details.append(f"{max_purchases_stars} orders via Stars ({stars_stickers} stickers)")
                
                logger.info(f"✅ SIMULATION: Would buy {max_purchases} total orders ({total_stickers} stickers)")
                logger.info(f"📊 Breakdown: {', '.join(purchase_details)}")
                
                if max_purchases_ton > 0:
                    logger.info(f"💰 SIMULATION: Would spend ~{total_cost:.2f} TON")
                
                # Send test notification
                await notifier.notify_purchase_success(
                    f"{collection.name} (DRY RUN)",
                    f"{character.name} (SIMULATED)",
                    max_purchases,
                    total_stickers,
                    total_cost,
                    "TON"  # Dry run with TON simulation
                )
            else:
                if 'TON' in settings.payment_methods and self.wallet:
                    character_price_ton = await self.api.get_character_price(collection_id, character_id, "TON")
                    required = (character_price_ton or character.price) * settings.stickers_per_purchase + settings.gas_amount
                    wallet_info = await self.wallet.get_wallet_info()
                    logger.info(f"❌ SIMULATION: Insufficient TON balance")
                    logger.info(f"💸 Would need: {required:.2f} TON, have: {wallet_info.balance_ton:.2f} TON")
                    
                    await notifier.notify_low_balance(wallet_info.balance_ton, required)
                
                if 'STARS' in settings.payment_methods:
                    logger.info(f"✅ Stars payment - ready to purchase when available")
            
            logger.info("🎭 Dry run completed successfully!")
            
        except Exception as e:
            logger.error(f"❌ Dry run failed: {e}")
            raise

    async def test_notifications_mode(self):
        """Test all notification types without any trading"""
        logger.info("🧪 Testing all notification types...")
        
        if not notifier.enabled:
            logger.error("❌ Telegram notifications not configured!")
            logger.info("Please set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in your .env file")
            return
        
        try:
            # Test 1: Bot started notification
            logger.info("1️⃣ Testing bot started notification...")
            await notifier.notify_bot_started(19, 2)
            await asyncio.sleep(1)
            
            # Test 2: Collection found notification
            logger.info("2️⃣ Testing collection found notification...")
            await notifier.notify_collection_found(
                collection_name="Crypto Cats TEST",
                character_name="Grumpy Cat TEST", 
                stock=150,
                price_stars=888,
                price_ton=None
            )
            await asyncio.sleep(1)
            
            # Test 3: Purchase success notification
            logger.info("3️⃣ Testing purchase success notification...")
            await notifier.notify_purchase_success(
                collection_name="Crypto Cats TEST",
                character_name="Grumpy Cat TEST",
                purchases=3,
                stickers=15,
                total_cost=13.14,
                currency="TON"  # Test notification with TON
            )
            await asyncio.sleep(1)
            
            # Test 3.5: Purchase success notification with Stars
            logger.info("3️⃣.5 Testing Stars purchase success notification...")
            await notifier.notify_purchase_success(
                collection_name="Crypto Cats TEST",
                character_name="Grumpy Cat TEST",
                purchases=2,
                stickers=10,
                total_cost=1776,
                currency="STARS"  # Test notification with Stars
            )
            await asyncio.sleep(1)
            
            # Test 3.6: Mixed payment notification
            logger.info("3️⃣.6 Testing mixed payment notification...")
            await notifier.notify_purchase_success(
                collection_name="Crypto Cats TEST",
                character_name="Grumpy Cat TEST",
                purchases=5,
                stickers=25,
                total_cost=1000,  # Primary display value
                currency="MIXED",
                combined_cost_text="💫 1000 Stars + 💰 5.50 TON"
            )
            await asyncio.sleep(1)
            
            # Test 4: Purchase failed notification
            logger.info("4️⃣ Testing purchase failed notification...")
            await notifier.notify_purchase_failed(
                collection_name="Crypto Cats TEST", 
                character_name="Grumpy Cat TEST",
                error="Insufficient balance for testing"
            )
            await asyncio.sleep(1)
            
            # Test 5: Low balance notification
            logger.info("5️⃣ Testing low balance notification...")
            await notifier.notify_low_balance(
                current_balance=0.5,
                required=22.5
            )
            await asyncio.sleep(1)
            
            # Test 5.5: Low Stars balance notification  
            logger.info("5️⃣.5 Testing low Stars balance notification...")
            await notifier.notify_low_balance(
                current_balance=50,
                required=2000,
                currency="STARS"
            )
            await asyncio.sleep(1)
            
            # Test 6: Custom test message
            logger.info("6️⃣ Testing custom test completion message...")
            await notifier.send_message(
                "🧪 <b>Notification Test Completed!</b>\n\n"
                "✅ All notification types have been tested\n"
                "📱 If you received all 9 messages, notifications are working correctly!\n\n"
                "🔔 Tested notifications:\n"
                "• Bot started\n"
                "• Collection found\n" 
                "• Purchase success (TON)\n"
                "• Purchase success (Stars)\n"
                "• Purchase success (Mixed)\n"
                "• Purchase failed\n"
                "• Low balance (TON)\n"
                "• Low balance (Stars)\n"
                "• Test completion\n\n"
                "<i>This was a test - no real purchases were made</i>"
            )
            
            logger.info("✅ All notification tests completed!")
            logger.info("📱 Check your Telegram to verify all 9 notifications were received")
            
        except Exception as e:
            logger.error(f"❌ Notification test failed: {e}")
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
  python main.py 2/19 --test-notifications # Test all Telegram notifications
  python main.py 2/19 --session-info     # Show Telegram session information
  python main.py 2/19 --logout-session   # Logout from Telegram and clear session
  python main.py 2/19 --clear-session    # Clear local session files only
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
        "--test-notifications",
        action="store_true",
        help="Test all notification types (no purchases, just Telegram messages)"
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
    
    args = parser.parse_args()
    
    # Validate arguments
    exclusive_args = [args.once, args.continuous, args.test, args.dry_run, args.test_notifications, 
                     args.session_info, args.logout_session, args.clear_session]
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
        elif args.test_notifications:
            # Test all notification types
            await bot.test_notifications_mode()
        elif args.session_info:
            # Show Telegram session info
            await bot.session_info_mode()
        elif args.logout_session:
            # Logout from Telegram
            await bot.logout_session_mode()
        elif args.clear_session:
            # Clear session files
            await bot.clear_session_mode()
        elif args.once:
            # One-time purchase mode
            await bot.initialize()
            
            try:
                results = await bot.orchestrator.execute_multiple_purchases(collection_id, character_id)
                successful = sum(1 for r in results if r.is_successful)
                
                if successful > 0:
                    total_stickers = successful * settings.stickers_per_purchase
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
    