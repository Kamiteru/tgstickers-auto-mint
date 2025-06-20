import asyncio
from typing import Optional
import aiohttp
from datetime import datetime

from config import settings
from utils.logger import logger


class TelegramNotifier:
    """Telegram notification system for trading alerts"""
    
    def __init__(self):
        self.bot_token = settings.telegram_bot_token
        self.chat_id = settings.telegram_chat_id
        self.enabled = bool(self.bot_token and self.chat_id)
        
        if self.enabled:
            logger.info("Telegram notifications enabled")
        else:
            logger.info("Telegram notifications disabled (missing configuration)")
    
    async def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """Send notification message to Telegram"""
        if not self.enabled:
            return False
        
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=10) as response:
                    if response.status == 200:
                        return True
                    else:
                        logger.error(f"Telegram notification failed: {response.status}")
                        return False
        except Exception as e:
            logger.error(f"Failed to send Telegram notification: {e}")
            return False
    
    async def notify_purchase_success(
        self, 
        collection_name: str, 
        character_name: str,
        purchases: int,
        stickers: int,
        total_cost: float,
        currency: str = "TON",
        combined_cost_text: str = None
    ):
        """Notify about successful purchase"""
        # Format cost display based on currency
        if currency == "STARS":
            cost_text = f"💫 Total Cost: <b>{int(total_cost)} Stars</b>"
        elif currency == "MIXED" and combined_cost_text:
            cost_text = f"💰 Total Cost: <b>{combined_cost_text}</b>"
        else:
            cost_text = f"💰 Total Cost: <b>{total_cost:.2f} {currency}</b>"
            
        text = (
            f"🎉 <b>Purchase Successful!</b>\n\n"
            f"📦 Collection: <b>{collection_name}</b>\n"
            f"🎭 Character: <b>{character_name}</b>\n"
            f"💳 Purchases: <b>{purchases}</b>\n"
            f"🏷️ Stickers: <b>{stickers}</b>\n"
            f"{cost_text}\n"
            f"⏰ Time: {datetime.now().strftime('%H:%M:%S')}"
        )
        await self.send_message(text)
    
    async def notify_purchase_failed(
        self, 
        collection_name: str, 
        character_name: str,
        error: str
    ):
        """Notify about failed purchase"""
        text = (
            f"❌ <b>Purchase Failed!</b>\n\n"
            f"📦 Collection: <b>{collection_name}</b>\n"
            f"🎭 Character: <b>{character_name}</b>\n"
            f"💥 Error: <code>{error}</code>\n"
            f"⏰ Time: {datetime.now().strftime('%H:%M:%S')}"
        )
        await self.send_message(text)
    
    async def notify_collection_found(
        self, 
        collection_name: str, 
        character_name: str,
        stock: int,
        price_stars: Optional[int] = None,
        price_ton: Optional[float] = None
    ):
        """Notify when collection becomes available"""
        # Show price in stars if available, otherwise TON
        if price_stars and price_stars > 0:
            price_text = f"💵 Price: <b>{price_stars} Stars per pack</b>"
        elif price_ton and price_ton > 0:
            price_text = f"💵 Price: <b>{price_ton} TON per pack</b>"
        else:
            price_text = "💵 Price: <b>Unknown</b>"
            
        text = (
            f"🔍 <b>Collection Available!</b>\n\n"
            f"📦 Collection: <b>{collection_name}</b>\n"
            f"🎭 Character: <b>{character_name}</b>\n"
            f"📊 Stock: <b>{stock}</b>\n"
            f"{price_text}\n"
            f"⏰ Time: {datetime.now().strftime('%H:%M:%S')}"
        )
        await self.send_message(text)
    
    async def notify_bot_started(self, collection_id: int, character_id: int):
        """Notify when bot starts monitoring"""
        text = (
            f"🤖 <b>Bot Started!</b>\n\n"
            f"🎯 Target: Collection {collection_id}, Character {character_id}\n"
            f"⏰ Started: {datetime.now().strftime('%H:%M:%S')}"
        )
        await self.send_message(text)
    
    async def notify_low_balance(self, current_balance: float, required: float, currency: str = "TON"):
        """Notify about low balance"""
        if currency == "STARS":
            text = (
                f"⚠️ <b>Low Balance Warning!</b>\n\n"
                f"💫 Current: <b>{int(current_balance)} Stars</b>\n"
                f"💸 Required: <b>{int(required)} Stars</b>\n"
                f"⏰ Time: {datetime.now().strftime('%H:%M:%S')}"
            )
        else:
            text = (
                f"⚠️ <b>Low Balance Warning!</b>\n\n"
                f"💰 Current: <b>{current_balance:.2f} {currency}</b>\n"
                f"💸 Required: <b>{required:.2f} {currency}</b>\n"
                f"⏰ Time: {datetime.now().strftime('%H:%M:%S')}"
            )
        await self.send_message(text)


# Global notifier instance
notifier = TelegramNotifier() 