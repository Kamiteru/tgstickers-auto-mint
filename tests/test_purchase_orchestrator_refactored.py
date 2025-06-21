import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch

from services.purchase_orchestrator import PurchaseOrchestrator
from services.api_client import StickerdomAPI
from services.validators import PurchaseValidator, SecurityValidator
from services.payment_factory import PaymentMethodFactory
from models import CollectionInfo, CharacterInfo
from exceptions import ValidationError, APIError


@pytest.mark.asyncio
class TestPurchaseOrchestratorRefactored:
    
    @pytest.fixture
    def mock_api_client(self):
        """Mock API client"""
        api = Mock(spec=StickerdomAPI)
        api.get_collection = AsyncMock()
        api.get_character_price = AsyncMock()
        api.initiate_purchase = AsyncMock()
        return api
    
    @pytest.fixture
    def mock_character(self):
        """Mock character"""
        return CharacterInfo(
            id=1,
            name="Test Character",
            left=10,
            price=5.0,
            total=100,
            rarity="common"
        )
    
    @pytest.fixture
    def mock_collection(self, mock_character):
        """Mock collection"""
        return CollectionInfo(
            id=1,
            name="Test Collection",
            status="active",
            characters=[mock_character],
            total_characters=1
        )
    
    async def test_orchestrator_initialization(self, mock_api_client):
        """Test orchestrator initialization"""
        with patch('services.purchase_orchestrator.settings') as mock_settings:
            mock_settings.payment_methods = ['TON']
            
            # Mock the payment factory to avoid dependency issues
            with patch('services.purchase_orchestrator.PaymentMethodFactory') as mock_factory:
                mock_factory_instance = Mock()
                mock_factory_instance.create_all_strategies.return_value = {}
                mock_factory.return_value = mock_factory_instance
                
                orchestrator = PurchaseOrchestrator(mock_api_client)
                
                assert orchestrator.api == mock_api_client
                assert isinstance(orchestrator.validator, PurchaseValidator)
                assert isinstance(orchestrator.security_validator, SecurityValidator)
    
    async def test_validator_input_validation(self):
        """Test input validation"""
        validator = PurchaseValidator()
        
        # Test valid parameters
        validator.validate_purchase_params(1, 1, 5)
        
        # Test invalid parameters
        with pytest.raises(ValidationError):
            validator.validate_purchase_params(-1, 1, 5)  # Invalid collection_id
        
        with pytest.raises(ValidationError):
            validator.validate_purchase_params(1, -1, 5)  # Invalid character_id
        
        with pytest.raises(ValidationError):
            validator.validate_purchase_params(1, 1, -5)  # Invalid count
        
        with pytest.raises(ValidationError):
            validator.validate_purchase_params(1, 1, 150)  # Count too high
    
    async def test_payment_method_validation(self):
        """Test payment method validation"""
        validator = PurchaseValidator()
        
        # Test valid methods
        assert validator.validate_payment_method('TON') == 'TON'
        assert validator.validate_payment_method('STARS') == 'STARS'
        
        # Test invalid method
        with pytest.raises(ValidationError):
            validator.validate_payment_method('INVALID')
    
    async def test_max_purchases_calculation(self):
        """Test max purchases calculation with validation"""
        validator = PurchaseValidator()
        
        # Test valid calculation
        max_purchases, total_cost = validator.validate_max_purchases_calculation(
            balance=10.0,
            price_per_pack=1.0, 
            stickers_per_purchase=5
        )
        
        assert max_purchases > 0
        assert total_cost > 0
        
        # Test insufficient balance
        max_purchases, total_cost = validator.validate_max_purchases_calculation(
            balance=0.5,
            price_per_pack=1.0,
            stickers_per_purchase=5
        )
        
        assert max_purchases == 0
        assert total_cost == 0
    
    async def test_character_availability_validation(self):
        """Test character availability validation"""
        validator = PurchaseValidator()
        
        # Mock character with stock
        character = Mock()
        character.id = 1
        character.is_available = True
        character.left = 10
        
        # Test normal case
        adjusted_count = validator.validate_character_availability(character, 5)
        assert adjusted_count == 5
        
        # Test stock limitation
        adjusted_count = validator.validate_character_availability(character, 15)
        assert adjusted_count == 10  # Should be limited to available stock
        
        # Test unavailable character
        character.is_available = False
        with pytest.raises(Exception):  # Should raise CollectionNotAvailableError
            validator.validate_character_availability(character, 5)
    
    async def test_security_validation(self):
        """Test security validation"""
        security_validator = SecurityValidator()
        
        # Test valid transaction
        security_validator.validate_transaction_limits(50.0, daily_limit=100.0)
        
        # Test transaction exceeds limit
        with pytest.raises(Exception):  # Should raise SecurityError
            security_validator.validate_transaction_limits(150.0, daily_limit=100.0)
        
        # Test valid purchase rate
        security_validator.validate_purchase_rate(10, time_window_minutes=60, max_per_window=50)
        
        # Test excessive purchase rate
        with pytest.raises(Exception):  # Should raise SecurityError
            security_validator.validate_purchase_rate(100, time_window_minutes=60, max_per_window=50)
    
    async def test_get_available_payment_methods(self, mock_api_client):
        """Test getting available payment methods"""
        with patch('services.purchase_orchestrator.settings') as mock_settings:
            mock_settings.payment_methods = ['TON', 'STARS']
            
            with patch('services.purchase_orchestrator.PaymentMethodFactory') as mock_factory:
                mock_factory_instance = Mock()
                mock_factory_instance.create_all_strategies.return_value = {
                    'TON': Mock(),
                    'STARS': Mock()
                }
                mock_factory.return_value = mock_factory_instance
                
                orchestrator = PurchaseOrchestrator(mock_api_client)
                available_methods = orchestrator.get_available_payment_methods()
                
                assert 'TON' in available_methods
                assert 'STARS' in available_methods
    
    async def test_orchestrator_status(self, mock_api_client):
        """Test orchestrator status"""
        with patch('services.purchase_orchestrator.settings') as mock_settings:
            mock_settings.payment_methods = ['TON']
            
            with patch('services.purchase_orchestrator.PaymentMethodFactory') as mock_factory:
                mock_factory_instance = Mock()
                mock_factory_instance.create_all_strategies.return_value = {'TON': Mock()}
                mock_factory.return_value = mock_factory_instance
                
                orchestrator = PurchaseOrchestrator(mock_api_client)
                status = orchestrator.get_orchestrator_status()
                
                assert 'available_strategies' in status
                assert 'configured_methods' in status
                assert 'cache_enabled' in status
                assert 'validator_enabled' in status
                assert status['legacy_mode'] is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"]) 