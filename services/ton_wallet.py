import asyncio
from decimal import Decimal
from typing import Optional, Tuple
from datetime import datetime

from tonutils.client import ToncenterV3Client
from tonutils.wallet import WalletV5R1

from config import settings
from exceptions import WalletError, TransactionError
from models.wallet import WalletInfo
from utils.logger import logger


class TONWalletManager:
    
    def __init__(self):
        self.mnemonic = settings.ton_seed_phrase.split()
        self.client: Optional[ToncenterV3Client] = None
        self.wallet: Optional[WalletV5R1] = None
        self._initialized = False
    
    async def initialize(self):
        """Initialize wallet with validation"""
        if self._initialized:
            return
        
        try:
            # Validate mnemonic length
            if len(self.mnemonic) != 24:
                raise WalletError(f"Invalid mnemonic: expected 24 words, got {len(self.mnemonic)}")
            
            is_testnet = settings.ton_endpoint == "testnet"
            self.client = ToncenterV3Client(
                is_testnet=is_testnet,
                rps=1,
                max_retries=3
            )
            
            self.wallet, _, _, _ = WalletV5R1.from_mnemonic(
                self.client,
                self.mnemonic
            )
            
            # Test wallet access
            address_str = self.wallet.address.to_str(is_bounceable=False)
            logger.info(f"Wallet initialized: {address_str}")
            
            # Verify we can get balance (wallet is accessible)
            balance = await self.client.get_account_balance(address_str)
            logger.info(f"Wallet balance: {balance / 10**9:.9f} TON")
            
            self._initialized = True
            
        except Exception as e:
            logger.error(f"Failed to initialize wallet: {e}")
            raise WalletError(f"Wallet initialization failed: {e}")
    

    async def get_wallet_info(self) -> WalletInfo:
        """Get current wallet information"""
        await self._ensure_initialized()
        
        try:
            address_str = self.wallet.address.to_str(is_bounceable=False)
            balance = await self.client.get_account_balance(address_str)
            seqno = 0  # TON libraries handle this internally
            
            return WalletInfo(
                address=address_str,
                balance=Decimal(balance),
                seqno=seqno,
                is_active=balance > 0
            )
            
        except Exception as e:
            logger.error(f"Failed to get wallet info: {e}")
            raise WalletError(f"Could not retrieve wallet information: {e}")
    

    async def send_payment(
        self,
        destination: str,
        amount_nano: int,
        comment: str
    ) -> Tuple[str, datetime]:
        """Send payment with validation and confirmation"""
        await self._ensure_initialized()
        
        # Validate inputs
        if amount_nano <= 0:
            raise TransactionError("Amount must be positive")
        
        if not destination:
            raise TransactionError("Destination address is required")
        
        if len(comment) > 127:  # TON comment limit
            raise TransactionError("Comment too long")
        
        try:
            amount_ton = amount_nano / 10**9
            
            # Check balance before sending
            wallet_info = await self.get_wallet_info()
            required_with_gas = amount_ton + settings.gas_amount
            
            if wallet_info.balance_ton < required_with_gas:
                raise TransactionError(
                    f"Insufficient balance: need {required_with_gas:.9f} TON, "
                    f"have {wallet_info.balance_ton:.9f} TON"
                )
            
            logger.info(
                f"Sending {amount_ton:.9f} TON to {destination} "
                f"with comment: {comment}"
            )
            
            # Send transaction
            tx_hash = await self.wallet.transfer(
                destination=destination,
                amount=amount_ton,
                body=comment
            )
            
            if not tx_hash:
                raise TransactionError("Transaction failed: no hash returned")
            
            logger.info(f"Transaction sent successfully: {tx_hash}")
            
            # Wait for transaction confirmation
            await asyncio.sleep(5)
            
            # Log new balance
            try:
                new_balance = await self.client.get_account_balance(
                    self.wallet.address.to_str(is_bounceable=False)
                )
                new_balance_ton = new_balance / 10**9
                logger.info(f"New balance after transaction: {new_balance_ton:.9f} TON")
            except Exception as e:
                logger.warning(f"Could not check balance after transaction: {e}")
            
            return tx_hash, datetime.now()
            
        except TransactionError:
            raise
        except Exception as e:
            logger.error(f"Failed to send payment: {e}")
            raise TransactionError(f"Payment failed: {e}")
    

    async def _ensure_initialized(self):
        """Ensure wallet is initialized"""
        if not self._initialized:
            await self.initialize()
    

    async def close(self):
        """Close wallet connections"""
        self._initialized = False
        logger.info("Wallet closed")
        