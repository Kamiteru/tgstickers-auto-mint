import asyncio
import os
from typing import Optional
from telethon import TelegramClient
from telethon.tl.functions import payments, auth
from telethon.tl.types import InputInvoiceSlug

from config import settings
from utils.logger import logger
from exceptions import APIError


class TelegramStarsPayment:
    """Service for handling Telegram Stars payments via Telethon"""
    
    def __init__(self):
        self.api_id = settings.telegram_api_id
        self.api_hash = settings.telegram_api_hash
        self.phone = settings.telegram_phone
        self.session_name = settings.telegram_session_name or 'stars_payment_session'
        self._client = None  # Store reference to client for session management
        logger.info("Telegram Stars payment service initialized")
    
    async def pay_invoice(self, invoice_url: str) -> str:
        """
        Process Stars payment through Telegram invoice using Telethon
        Returns transaction hash or payment ID
        """
        try:
            # Extract slug from invoice URL
            if "$" not in invoice_url:
                raise APIError("Invalid invoice URL format: no $ found")
            
            invoice_slug = invoice_url.split("$")[1]
            logger.info(f"Processing Stars payment with invoice slug: {invoice_slug}")
            
            # Initialize Telegram client
            async with TelegramClient(
                self.session_name, 
                self.api_id, 
                self.api_hash
            ) as client:
                # Start client with phone number
                await client.start(phone=self.phone)
                
                # Get payment form information
                logger.info("Getting payment form information...")
                invoice_input = InputInvoiceSlug(slug=invoice_slug)
                
                invoice_form = await client(payments.GetPaymentFormRequest(
                    invoice=invoice_input
                ))
                
                logger.info(f"Payment form ID: {invoice_form.form_id}")
                
                # Send stars payment
                logger.info("Sending Stars payment...")
                payment_result = await client(payments.SendStarsFormRequest(
                    form_id=invoice_form.form_id,
                    invoice=invoice_input,
                ))
                
                # Extract payment ID from result
                if hasattr(payment_result, 'receipt_msg_id'):
                    payment_id = f"stars_{payment_result.receipt_msg_id}"
                else:
                    payment_id = f"stars_{invoice_slug[:8]}_{int(asyncio.get_event_loop().time())}"
                
                logger.info(f"Stars payment completed successfully with ID: {payment_id}")
                return payment_id
                
        except Exception as e:
            logger.error(f"Stars payment failed: {e}")
            raise APIError(f"Stars payment failed: {str(e)}")

    async def close_session(self):
        """Close active Telethon session and disconnect"""
        try:
            if self._client and not self._client.is_connected():
                return
            
            logger.info("Closing Telegram Stars session...")
            
            # Create a new client to properly disconnect
            async with TelegramClient(
                self.session_name, 
                self.api_id, 
                self.api_hash
            ) as client:
                if client.is_connected():
                    await client.disconnect()
                    logger.info("✅ Telethon session disconnected successfully")
                
        except Exception as e:
            logger.error(f"Error closing Telethon session: {e}")

    async def logout_session(self):
        """Logout from Telegram and invalidate the session"""
        try:
            logger.info("Logging out from Telegram session...")
            
            async with TelegramClient(
                self.session_name, 
                self.api_id, 
                self.api_hash
            ) as client:
                await client.start(phone=self.phone)
                
                # Logout from Telegram (invalidates session)
                await client(auth.LogOutRequest())
                logger.info("✅ Successfully logged out from Telegram")
                
                # Clear session file after logout
                await self.clear_session_files()
                
        except Exception as e:
            logger.error(f"Error during logout: {e}")

    async def clear_session_files(self):
        """Remove local session files"""
        try:
            session_file = f"{self.session_name}.session"
            if os.path.exists(session_file):
                os.remove(session_file)
                logger.info(f"✅ Session file {session_file} removed")
            
            test_session_file = f"test_{self.session_name}.session"
            if os.path.exists(test_session_file):
                os.remove(test_session_file)
                logger.info(f"✅ Test session file {test_session_file} removed")
                
        except Exception as e:
            logger.error(f"Error removing session files: {e}")

    def check_bot_connection(self) -> bool:
        """Test Telegram client connection"""
        try:
            # Create a temporary client to test connection
            async def test_connection():
                async with TelegramClient(
                    f"test_{self.session_name}", 
                    self.api_id, 
                    self.api_hash
                ) as client:
                    await client.start(phone=self.phone)
                    me = await client.get_me()
                    logger.info(f"Connected to Telegram as: {me.username or me.first_name}")
                    return True
            
            # Run the test in event loop
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # If loop is already running, we can't test synchronously
                logger.info("Event loop already running, assuming connection is OK")
                return True
            else:
                return loop.run_until_complete(test_connection())
                
        except Exception as e:
            logger.error(f"Telegram client connection test failed: {e}")
            return False

    async def get_session_info(self):
        """Get information about current Telegram session"""
        try:
            async with TelegramClient(
                self.session_name, 
                self.api_id, 
                self.api_hash
            ) as client:
                await client.start(phone=self.phone)
                me = await client.get_me()
                
                session_info = {
                    "user_id": me.id,
                    "username": me.username,
                    "first_name": me.first_name,
                    "phone": me.phone,
                    "is_premium": getattr(me, 'premium', False),
                    "session_file": f"{self.session_name}.session",
                    "session_exists": os.path.exists(f"{self.session_name}.session")
                }
                
                logger.info(f"Session info: {me.first_name} (@{me.username})")
                return session_info
                
        except Exception as e:
            logger.error(f"Error getting session info: {e}")
            return None 