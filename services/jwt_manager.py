import asyncio
import os
import time
import json
import logging
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Optional, Dict, Any
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.common.exceptions import TimeoutException, WebDriverException


@dataclass
class JWTConfig:
    """Configuration for JWT Manager"""
    env_file_path: str = '.env'
    env_token_key: str = 'STICKERDOM_JWT_TOKEN'
    chrome_profile_path: str = '~/.config/google-chrome/Default'
    telegram_chat_url: str = 'https://web.telegram.org/a/#7686366470'
    app_url: str = 'https://stickerdom.store/'
    token_cache_duration: int = 3600  # 1 hour in seconds
    page_load_timeout: int = 15
    token_wait_timeout: int = 10
    max_retries: int = 3


class TokenCache:
    """Simple in-memory token cache with TTL"""
    
    def __init__(self):
        self._token: Optional[str] = None
        self._expires_at: Optional[datetime] = None
    
    def get(self) -> Optional[str]:
        """Get cached token if still valid"""
        if self._token and self._expires_at and datetime.now() < self._expires_at:
            return self._token
        return None
    
    def set(self, token: str, ttl_seconds: int):
        """Cache token with TTL"""
        self._token = token
        self._expires_at = datetime.now() + timedelta(seconds=ttl_seconds)
    
    def clear(self):
        """Clear cached token"""
        self._token = None
        self._expires_at = None
    
    def is_valid(self) -> bool:
        """Check if cached token is still valid"""
        return self.get() is not None


class WebDriverManager:
    """Manages Chrome WebDriver instance"""
    
    def __init__(self, config: JWTConfig):
        self.config = config
        self.logger = logging.getLogger(__name__)
    
    def create_driver(self) -> webdriver.Chrome:
        """Create configured Chrome driver"""
        profile_path = Path(self.config.chrome_profile_path).expanduser()
        service = Service(ChromeDriverManager().install())
        
        options = webdriver.ChromeOptions()
        options.add_argument(f'--user-data-dir={profile_path.parent}')
        options.add_argument(f'--profile-directory={profile_path.name}')
        options.add_argument('--disable-gpu')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-web-security')
        options.add_argument('--disable-features=VizDisplayCompositor')
        options.set_capability('goog:loggingPrefs', {'performance': 'ALL'})
        
        return webdriver.Chrome(service=service, options=options)


class JWTManager:
    """Manages JWT token retrieval, caching, and storage"""
    
    def __init__(self, config: Optional[JWTConfig] = None):
        self.config = config or JWTConfig()
        self.cache = TokenCache()
        self.driver_manager = WebDriverManager(self.config)
        self.logger = logging.getLogger(__name__)
        
        # Setup logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
    
    async def get_token(self, force_refresh: bool = False) -> Optional[str]:
        """
        Get JWT token with caching
        
        Args:
            force_refresh: If True, bypass cache and fetch new token
            
        Returns:
            JWT token string or None if failed
        """
        # Return cached token if valid and not forcing refresh
        if not force_refresh:
            cached_token = self.cache.get()
            if cached_token:
                self.logger.info("✅ Using cached token")
                return cached_token
        
        # Fetch new token
        self.logger.info("🔄 Fetching new token...")
        loop = asyncio.get_running_loop()
        token = await loop.run_in_executor(None, self._fetch_token_with_retry)
        
        if token:
            # Cache the token
            self.cache.set(token, self.config.token_cache_duration)
            # Save to .env file
            self._update_env_token(token)
            self.logger.info("✅ Token obtained and cached")
            return token
        
        self.logger.error("❌ Failed to obtain token")
        return None
    
    def _fetch_token_with_retry(self) -> Optional[str]:
        """Fetch token with retry mechanism"""
        last_exception = None
        
        for attempt in range(1, self.config.max_retries + 1):
            try:
                self.logger.info(f"🔄 Token fetch attempt {attempt}/{self.config.max_retries}")
                token = self._fetch_token()
                if token:
                    return token
            except Exception as e:
                last_exception = e
                self.logger.warning(f"⚠️ Attempt {attempt} failed: {e}")
                if attempt < self.config.max_retries:
                    time.sleep(2 ** attempt)  # Exponential backoff
        
        self.logger.error(f"❌ All attempts failed. Last error: {last_exception}")
        return None
    
    def _fetch_token(self) -> Optional[str]:
        """Core token fetching logic"""
        with self.driver_manager.create_driver() as driver:
            # Enable network logging
            driver.execute_cdp_cmd('Network.enable', {})
            driver.execute_cdp_cmd('Runtime.enable', {})
            
            # Method 1: Try to get token via Telegram Web
            token = self._try_telegram_flow(driver)
            if token:
                return token
            
            # Method 2: Direct app access
            token = self._try_direct_app_access(driver)
            if token:
                return token
            
            return None
    
    def _try_telegram_flow(self, driver: webdriver.Chrome) -> Optional[str]:
        """Try to get token through Telegram Web flow"""
        try:
            self.logger.info("📱 Trying Telegram Web flow...")
            driver.get(self.config.telegram_chat_url)
            time.sleep(8)
            
            # Look for Open button
            mini_app_url = self._find_and_click_open_button(driver)
            if not mini_app_url:
                self.logger.warning("⚠️ Could not find mini-app URL via Telegram")
                return None
            
            # Navigate to mini-app and get token
            return self._extract_token_from_app(driver, mini_app_url)
            
        except Exception as e:
            self.logger.error(f"❌ Telegram flow failed: {e}")
            return None
    
    def _try_direct_app_access(self, driver: webdriver.Chrome) -> Optional[str]:
        """Try direct access to the app"""
        try:
            self.logger.info("🌐 Trying direct app access...")
            return self._extract_token_from_app(driver, self.config.app_url)
        except Exception as e:
            self.logger.error(f"❌ Direct app access failed: {e}")
            return None
    
    def _find_and_click_open_button(self, driver: webdriver.Chrome) -> Optional[str]:
        """Find and click the Open button, return mini-app URL"""
        try:
            # Wait for page load
            time.sleep(5)
            
            # Try to find Open button
            button = None
            try:
                button = WebDriverWait(driver, self.config.page_load_timeout).until(
                    EC.element_to_be_clickable((By.XPATH, '//span[contains(text(), "Open")]/ancestor::button'))
                )
                self.logger.info("🔍 Open button found")
            except TimeoutException:
                self.logger.info("🔍 Searching for alternative buttons...")
                # Search for buttons with relevant text
                buttons = driver.find_elements(By.TAG_NAME, "button")
                for btn in buttons:
                    try:
                        text = btn.text.strip().lower()
                        if any(word in text for word in ['open', 'launch', 'start', 'открыть', 'запустить']):
                            button = btn
                            self.logger.info(f"🔍 Found button: '{btn.text.strip()}'")
                            break
                    except:
                        continue
            
            # Click button if found
            if button:
                try:
                    button.click()
                    self.logger.info("👆 Button clicked")
                except:
                    driver.execute_script("arguments[0].click();", button)
                    self.logger.info("👆 Button clicked via JavaScript")
                
                time.sleep(10)
            
            # Extract mini-app URL from performance entries or iframe
            return self._extract_mini_app_url(driver)
            
        except Exception as e:
            self.logger.error(f"❌ Error finding Open button: {e}")
            return None
    
    def _extract_mini_app_url(self, driver: webdriver.Chrome) -> Optional[str]:
        """Extract mini-app URL from page"""
        # Try performance entries
        mini_app_url = driver.execute_script("""
            const entries = performance.getEntries();
            let stickerEntry = entries.find(e => e.name.includes('stickerdom.store')) ||
                              entries.find(e => e.name.includes('stickerdom')) ||
                              entries.find(e => e.name.includes('mini-app'));
            return stickerEntry ? stickerEntry.name : '';
        """)
        
        if mini_app_url:
            self.logger.info(f"🔗 Found mini-app URL in performance: {mini_app_url}")
            return mini_app_url
        
        # Try iframe
        try:
            iframe = driver.find_element(By.TAG_NAME, "iframe")
            mini_app_url = iframe.get_attribute("src")
            if mini_app_url and "stickerdom" in mini_app_url:
                self.logger.info(f"🔗 Found mini-app URL in iframe: {mini_app_url}")
                return mini_app_url
        except:
            pass
        
        self.logger.warning("⚠️ Mini-app URL not found")
        return None
    
    def _extract_token_from_app(self, driver: webdriver.Chrome, app_url: str) -> Optional[str]:
        """Extract JWT token from app"""
        self.logger.info(f"🌐 Navigating to: {app_url}")
        driver.get(app_url)
        time.sleep(self.config.token_wait_timeout)
        
        # Check performance logs for auth requests
        logs = driver.get_log('performance')
        self.logger.info(f"📋 Retrieved {len(logs)} log entries")
        
        for entry in logs:
            try:
                log = json.loads(entry['message'])
                msg = log.get('message', {})
                
                if msg.get('method') == 'Network.responseReceived':
                    params = msg.get('params', {})
                    response = params.get('response', {})
                    url = response.get('url', '')
                    
                    if 'api/v1/auth' in url or 'auth' in url.lower():
                        self.logger.info(f"🔍 Found auth request: {url}")
                        request_id = params.get('requestId')
                        
                        if request_id:
                            token = self._extract_token_from_response(driver, request_id)
                            if token:
                                return token
                                
            except Exception as e:
                self.logger.debug(f"Error parsing log entry: {e}")
                continue
        
        self.logger.warning("⚠️ No auth token found in logs")
        return None
    
    def _extract_token_from_response(self, driver: webdriver.Chrome, request_id: str) -> Optional[str]:
        """Extract token from network response"""
        try:
            body = driver.execute_cdp_cmd('Network.getResponseBody', {'requestId': request_id})
            if 'body' in body:
                data = json.loads(body['body'])
                token = data.get('data')
                if token:
                    self.logger.info("🎯 Token extracted from response")
                    return token
        except Exception as e:
            self.logger.debug(f"Error extracting token from response: {e}")
        
        return None
    
    def _update_env_token(self, new_token: str):
        """Update JWT token in .env file"""
        try:
            env_path = Path(self.config.env_file_path)
            lines = []
            token_found = False
            
            # Read existing file
            if env_path.exists():
                with open(env_path, 'r', encoding='utf-8') as file:
                    lines = file.readlines()
            
            # Update or add token line
            token_line = f'{self.config.env_token_key}={new_token}\n'
            for i, line in enumerate(lines):
                if line.strip().startswith(f'{self.config.env_token_key}='):
                    lines[i] = token_line
                    token_found = True
                    break
            
            if not token_found:
                lines.append(token_line)
            
            # Write back to file
            with open(env_path, 'w', encoding='utf-8') as file:
                file.writelines(lines)
            
            self.logger.info(f"💾 Token updated in {env_path}")
            
        except Exception as e:
            self.logger.error(f"❌ Failed to update .env file: {e}")
    
    def clear_cache(self):
        """Clear token cache"""
        self.cache.clear()
        self.logger.info("🗑️ Token cache cleared")
    
    def get_cache_status(self) -> Dict[str, Any]:
        """Get cache status information"""
        return {
            'has_cached_token': self.cache.is_valid(),
            'expires_at': self.cache._expires_at.isoformat() if self.cache._expires_at else None,
            'time_until_expiry': (
                int((self.cache._expires_at - datetime.now()).total_seconds()) 
                if self.cache._expires_at and self.cache._expires_at > datetime.now() 
                else 0
            )
        }


# Convenience functions for backward compatibility
async def get_token() -> Optional[str]:
    """Get JWT token (backward compatibility)"""
    manager = JWTManager()
    return await manager.get_token()


def update_env_token(new_token: str):
    """Update JWT token in .env file (backward compatibility)"""
    manager = JWTManager()
    manager._update_env_token(new_token)


# Example usage
async def main():
    """Example usage of JWTManager"""
    # Create manager with custom config
    config = JWTConfig(
        token_cache_duration=7200,  # 2 hours
        max_retries=2
    )
    manager = JWTManager(config)
    
    # Get token (will use cache if available)
    token = await manager.get_token()
    if token:
        print(f"Token obtained: {token[:20]}...")
        
        # Check cache status
        status = manager.get_cache_status()
        print(f"Cache status: {status}")
        
        # Force refresh if needed
        # new_token = await manager.get_token(force_refresh=True)
    else:
        print("Failed to obtain token")


if __name__ == "__main__":
    asyncio.run(main())