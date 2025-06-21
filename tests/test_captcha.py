#!/usr/bin/env python3
"""
Test Captcha System - тестирование системы решения капч
"""

import asyncio
import sys
import os
import pytest

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.captcha_solver import CaptchaManager, CaptchaChallenge
from utils.notifications import TelegramNotifier
from utils.logger import logger


@pytest.mark.asyncio
async def test_captcha_detection():
    """Тест обнаружения капчи в ответах"""
    logger.info("🧪 Testing captcha detection...")
    
    notifier = TelegramNotifier()
    captcha_manager = CaptchaManager(notifier)
    
    # Тестовые данные с различными типами капч
    test_responses = [
        # reCAPTCHA
        {
            "error": "captcha_required",
            "captcha_type": "recaptcha",
            "site_key": "6LeIxAcTAAAAAJcZVRqyHh71UMIEGNQ_MXjiZKhI"
        },
        # hCaptcha
        {
            "error": "verification_required",
            "hcaptcha": {
                "site_key": "10000000-ffff-ffff-ffff-000000000001"
            }
        },
        # Простая капча
        {
            "message": "Please solve captcha",
            "captcha": "required"
        },
        # Нормальный ответ
        {
            "ok": True,
            "data": {"order_id": "test"}
        }
    ]
    
    for i, response in enumerate(test_responses):
        logger.info(f"\n--- Test Response {i+1} ---")
        challenge = captcha_manager.detect_captcha(response)
        
        if challenge:
            logger.info(f"✅ Captcha detected: {challenge.captcha_type}")
            logger.info(f"   Site URL: {challenge.site_url}")
            logger.info(f"   Site Key: {challenge.site_key}")
        else:
            logger.info("⚪ No captcha detected")


@pytest.mark.asyncio
async def test_manual_captcha():
    """Тест ручного решения капчи"""
    logger.info("\n🤖 Testing manual captcha solving...")
    
    notifier = TelegramNotifier()
    captcha_manager = CaptchaManager(notifier)
    
    # Создаем тестовую капчу
    challenge = CaptchaChallenge(
        captcha_type="test_captcha",
        site_url="https://stickerdom.store",
        site_key="test_key"
    )
    
    logger.info("📝 Creating captcha_solved.flag file for testing...")
    with open('captcha_solved.flag', 'w') as f:
        f.write('test_solution_token')
    
    try:
        solution = await captcha_manager.solve_captcha(challenge)
        logger.info(f"✅ Solution received: {solution.token}")
        logger.info(f"   Method: {solution.solver_method}")
        logger.info(f"   Time: {solution.solution_time:.1f}s")
    except Exception as e:
        logger.error(f"❌ Manual captcha test failed: {e}")


@pytest.mark.asyncio
async def test_service_integration():
    """Тест интеграции с сервисами решения капч"""
    logger.info("\n🌐 Testing captcha service integration...")
    
    # Проверяем наличие API ключей
    from config import settings
    
    if hasattr(settings, 'anticaptcha_api_key') and settings.anticaptcha_api_key:
        logger.info("✅ Anti-captcha API key configured")
    else:
        logger.warning("⚠️ Anti-captcha API key not configured")
    
    if settings.captcha_enabled:
        logger.info("✅ Captcha solving enabled")
    else:
        logger.warning("⚠️ Captcha solving disabled")


async def main():
    if len(sys.argv) > 1:
        test_type = sys.argv[1]
    else:
        test_type = "all"
    
    logger.info("🔐 Starting Captcha System Tests")
    logger.info("="*50)
    
    try:
        if test_type in ["all", "detection"]:
            await test_captcha_detection()
        
        if test_type in ["all", "manual"]:
            await test_manual_captcha()
        
        if test_type in ["all", "integration"]:
            await test_service_integration()
        
        logger.info("\n" + "="*50)
        logger.info("✅ All captcha tests completed!")
        
    except Exception as e:
        logger.error(f"❌ Captcha tests failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    print("Usage: python test_captcha.py [test_type]")
    print("test_types: all (default), detection, manual, integration")
    print()
    asyncio.run(main()) 