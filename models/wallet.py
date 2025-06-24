from dataclasses import dataclass
from decimal import Decimal


@dataclass
class WalletInfo:
    address: str
    balance: Decimal
    seqno: int
    is_active: bool
    
    
    @property
    def balance_ton(self) -> float:
        return float(self.balance / Decimal(10**9))
    

    def has_sufficient_balance(self, required_amount: float) -> bool:
        return self.balance_ton >= required_amount
    