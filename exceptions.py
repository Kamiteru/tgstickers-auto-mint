class StickerHunterError(Exception):
    pass


class APIError(StickerHunterError):
    pass


class WalletError(StickerHunterError):
    pass


class TransactionError(StickerHunterError):
    pass


class CollectionNotAvailableError(StickerHunterError):
    pass


class InsufficientBalanceError(WalletError):
    pass

class ConfigError(StickerHunterError):
    pass

class CaptchaError(StickerHunterError):
    """Error related to captcha solving operations"""
    pass


class ValidationError(StickerHunterError):
    """Error related to input validation"""
    pass


class PaymentStrategyError(StickerHunterError):
    """Error related to payment strategy operations"""
    pass


class PurchaseTimeoutError(StickerHunterError):
    """Error when purchase operations timeout"""
    pass


class SecurityError(StickerHunterError):
    """Error related to security validation"""
    pass
