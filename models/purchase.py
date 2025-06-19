from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional, List


class PurchaseStatus(Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    FAILED = "failed"
    TIMEOUT = "timeout"


@dataclass
class CharacterInfo:
    id: int
    name: str
    left: int
    price: float
    
    @property
    def is_available(self) -> bool:
        return self.left > 0


@dataclass
class CollectionInfo:
    id: int
    name: str
    status: str
    total_count: int
    sold_count: int
    characters: List[CharacterInfo]
    

    @property
    def is_active(self) -> bool:
        return self.status == "active"
    

    @property
    def available_characters(self) -> List[CharacterInfo]:
        return [char for char in self.characters if char.is_available]


@dataclass
class PurchaseRequest:
    collection_id: int
    character_id: int
    count: int
    price_per_item: float
    total_amount: Decimal
    order_id: str
    destination_wallet: str
    created_at: datetime
    
    
    @property
    def total_amount_ton(self) -> float:
        return float(self.total_amount / Decimal(10**9))


@dataclass
class PurchaseResult:
    request: PurchaseRequest
    transaction_hash: Optional[str]
    status: PurchaseStatus
    completed_at: Optional[datetime]
    error_message: Optional[str] = None
    

    @property
    def is_successful(self) -> bool:
        return self.status == PurchaseStatus.CONFIRMED
    