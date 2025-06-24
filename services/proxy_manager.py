import random
import os
from typing import List, Optional, Dict, Any
from urllib.parse import urlparse

from utils.logger import logger


class ProxyManager:
    """Manager for proxy rotation with random selection"""
    
    def __init__(self, proxies_file: str = 'proxies.txt'):
        self.proxies_file = proxies_file
        self.proxies: List[Dict[str, Any]] = []
        self.enabled = False
        self.load_proxies()
    
    def load_proxies(self) -> None:
        """Load proxies from file"""
        if not os.path.exists(self.proxies_file):
            logger.info(f"Proxy file {self.proxies_file} not found - running without proxies")
            return
        
        try:
            with open(self.proxies_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            self.proxies = []
            for line in lines:
                line = line.strip()
                if line and not line.startswith('#'):
                    proxy_config = self._parse_proxy(line)
                    if proxy_config:
                        self.proxies.append(proxy_config)
            
            if self.proxies:
                self.enabled = True
                logger.info(f"Loaded {len(self.proxies)} proxies from {self.proxies_file}")
            else:
                logger.warning(f"No valid proxies found in {self.proxies_file}")
                
        except Exception as e:
            logger.error(f"Failed to load proxies: {e}")
    
    def _parse_proxy(self, proxy_string: str) -> Optional[Dict[str, Any]]:
        """Parse proxy string into configuration"""
        try:
            # Handle simple host:port format
            if '://' not in proxy_string:
                if ':' in proxy_string:
                    host, port = proxy_string.split(':', 1)
                    return {
                        'protocol': 'http',
                        'host': host.strip(),
                        'port': int(port.strip()),
                        'url': f"http://{host.strip()}:{port.strip()}",
                        'original': proxy_string
                    }
                return None
            
            # Parse full URL format
            parsed = urlparse(proxy_string)
            if not parsed.hostname or not parsed.port:
                logger.warning(f"Invalid proxy format: {proxy_string}")
                return None
            
            config = {
                'protocol': parsed.scheme,
                'host': parsed.hostname,
                'port': parsed.port,
                'url': proxy_string,
                'original': proxy_string
            }
            
            if parsed.username:
                config['username'] = parsed.username
            if parsed.password:
                config['password'] = parsed.password
            
            return config
            
        except Exception as e:
            logger.warning(f"Failed to parse proxy '{proxy_string}': {e}")
            return None
    
    def get_random_proxy(self) -> Optional[Dict[str, Any]]:
        """Get random proxy configuration"""
        if not self.enabled or not self.proxies:
            return None
        
        return random.choice(self.proxies)
    
    def get_proxy_for_requests(self) -> Optional[Dict[str, str]]:
        """Get proxy configuration for requests/curl_cffi"""
        proxy_config = self.get_random_proxy()
        if not proxy_config:
            return None
        
        protocol = proxy_config['protocol'].lower()
        url = proxy_config['url']
        
        # Return format expected by requests/curl_cffi
        if protocol in ['http', 'https']:
            return {
                'http': url,
                'https': url
            }
        elif protocol in ['socks4', 'socks5']:
            return {
                'http': url,
                'https': url
            }
        else:
            logger.warning(f"Unsupported proxy protocol: {protocol}")
            return None
    
    def get_random_proxy_url(self) -> Optional[str]:
        """Get random proxy URL string"""
        proxy_config = self.get_random_proxy()
        return proxy_config['url'] if proxy_config else None
    
    def is_enabled(self) -> bool:
        """Check if proxy system is enabled"""
        return self.enabled
    
    def get_proxy_count(self) -> int:
        """Get number of loaded proxies"""
        return len(self.proxies)
    
    def reload_proxies(self) -> None:
        """Reload proxies from file"""
        logger.info("Reloading proxies...")
        self.load_proxies()


# Global proxy manager instance
proxy_manager = ProxyManager() 