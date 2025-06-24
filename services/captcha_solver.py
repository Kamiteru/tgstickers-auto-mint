#!/usr/bin/env python3
"""
Captcha Solver - system for solving different types of captchas
Uses official anticaptchaofficial library for maximum reliability
"""

import asyncio
import time
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
from dataclasses import dataclass

from anticaptchaofficial.recaptchav2proxyless import recaptchaV2Proxyless
from anticaptchaofficial.recaptchav3proxyless import recaptchaV3Proxyless  
from anticaptchaofficial.hcaptchaproxyless import hCaptchaProxyless
from anticaptchaofficial.turnstileproxyless import turnstileProxyless
from anticaptchaofficial.imagecaptcha import imagecaptcha

from config import settings
from utils.logger import logger
from exceptions import CaptchaError


@dataclass
class CaptchaChallenge:
    """Captcha data for solving"""
    captcha_type: str
    site_key: str = None
    site_url: str = None
    image_data: str = None
    question: str = None
    additional_data: Dict[str, Any] = None


@dataclass
class CaptchaSolution:
    """Captcha solution result"""
    token: str
    solution_time: float
    solver_method: str


class CaptchaSolver(ABC):
    """Base class for captcha solving"""
    
    @abstractmethod
    async def solve(self, challenge: CaptchaChallenge) -> CaptchaSolution:
        """Solve captcha"""
        pass
    
    @abstractmethod
    def supports(self, captcha_type: str) -> bool:
        """Check if the captcha type is supported"""
        pass


class AntiCaptchaOfficialSolver(CaptchaSolver):
    """Solving captchas through the official anti-captcha.com library"""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
    
    def supports(self, captcha_type: str) -> bool:
        return captcha_type in ['recaptcha_v2', 'recaptcha_v3', 'hcaptcha', 'turnstile', 'image']
    
    async def solve(self, challenge: CaptchaChallenge) -> CaptchaSolution:
        """Solving through the official anti-captcha library"""
        start_time = time.time()
        
        try:
            # Select appropriate solver based on captcha type
            solver = self._create_solver(challenge)
            if not solver:
                raise CaptchaError(f"Unsupported captcha type: {challenge.captcha_type}")
            
            # Configure solver parameters
            self._configure_solver(solver, challenge)
            
            # Run solving in executor to avoid blocking
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, solver.solve_and_return_solution)
            
            if not result:
                error_msg = solver.err_string if hasattr(solver, 'err_string') else "Unknown error"
                raise CaptchaError(f"Solving failed: {error_msg}")
            
            solve_time = time.time() - start_time
            logger.info(f"✅ Captcha solved in {solve_time:.1f}s via anti-captcha official")
            
            return CaptchaSolution(
                token=result,
                solution_time=solve_time,
                solver_method="anticaptcha_official"
            )
            
        except Exception as e:
            logger.error(f"❌ Anti-captcha official solving failed: {e}")
            raise CaptchaError(f"Anti-captcha official failed: {e}")
    
    def _create_solver(self, challenge: CaptchaChallenge):
        """Create appropriate solver instance"""
        if challenge.captcha_type == 'recaptcha_v2':
            return recaptchaV2Proxyless()
        elif challenge.captcha_type == 'recaptcha_v3':
            return recaptchaV3Proxyless()
        elif challenge.captcha_type == 'hcaptcha':
            return hCaptchaProxyless()
        elif challenge.captcha_type == 'turnstile':
            return turnstileProxyless()
        elif challenge.captcha_type == 'image':
            return imagecaptcha()
        return None
    
    def _configure_solver(self, solver, challenge: CaptchaChallenge):
        """Configure solver with challenge parameters"""
        solver.set_key(self.api_key)
        
        if challenge.captcha_type == 'recaptcha_v2':
            solver.set_website_url(challenge.site_url)
            solver.set_website_key(challenge.site_key)
        elif challenge.captcha_type == 'recaptcha_v3':
            solver.set_website_url(challenge.site_url)
            solver.set_website_key(challenge.site_key)
            solver.set_min_score(0.3)  # Default minimum score
            if challenge.additional_data and 'action' in challenge.additional_data:
                solver.set_page_action(challenge.additional_data['action'])
        elif challenge.captcha_type == 'hcaptcha':
            solver.set_website_url(challenge.site_url)
            solver.set_website_key(challenge.site_key)
        elif challenge.captcha_type == 'turnstile':
            solver.set_website_url(challenge.site_url)
            solver.set_website_key(challenge.site_key)
        elif challenge.captcha_type == 'image':
            solver.set_image_data(challenge.image_data)


# Previous implementation replaced with AntiCaptchaOfficialSolver


class ManualCaptchaSolver(CaptchaSolver):
    """Manual captcha solving with user notification"""
    
    def __init__(self):
        pass
    
    def supports(self, captcha_type: str) -> bool:
        return True  # Supports any captcha type
    
    async def solve(self, challenge: CaptchaChallenge) -> CaptchaSolution:
        """Manual solving with bot pause"""
        start_time = time.time()
        
        logger.warning("🚨 CAPTCHA DETECTED - Manual intervention required!")
        
        logger.info(f"Type: {challenge.captcha_type}")
        logger.info(f"Site: {challenge.site_url or 'stickerdom.store'}")
        logger.info("Bot is paused. Solve captcha manually and create 'captcha_solved.flag' file")
        
        # Wait for user signal (can add webhook or file check here)
        logger.info("⏳ Waiting for manual captcha solution...")
        
        # Simple implementation - wait for flag file
        while True:
            try:
                with open('captcha_solved.flag', 'r') as f:
                    token = f.read().strip()
                    break
            except FileNotFoundError:
                await asyncio.sleep(5)
                continue
        
        # Remove flag file
        import os
        os.remove('captcha_solved.flag')
        
        solve_time = time.time() - start_time
        logger.info(f"✅ Manual captcha solved in {solve_time:.1f}s")
        
        return CaptchaSolution(
            token=token or "manual_bypass",
            solution_time=solve_time,
            solver_method="manual"
        )


class CaptchaManager:
    """Main captcha management system"""
    
    def __init__(self):
        self.enabled = settings.captcha_enabled
        self.solvers = []
        self._setup_solvers()
    
    def _setup_solvers(self):
        """Setup available captcha solvers"""
        # Official anti-captcha.com solver is preferred
        if self.enabled and hasattr(settings, 'anticaptcha_api_key') and settings.anticaptcha_api_key:
            self.solvers.append(AntiCaptchaOfficialSolver(settings.anticaptcha_api_key))
            logger.info("✅ Anti-captcha official solver enabled")
        
        # Manual solver as fallback
        self.solvers.append(ManualCaptchaSolver())
        logger.info("✅ Manual captcha solver enabled as fallback")
    
    async def solve_captcha(self, challenge: CaptchaChallenge) -> CaptchaSolution:
        """Solve captcha using available methods"""
        
        logger.warning(f"🔐 Captcha detected: {challenge.captcha_type}")
        
        for solver in self.solvers:
            if solver.supports(challenge.captcha_type):
                try:
                    logger.info(f"🔧 Trying solver: {solver.__class__.__name__}")
                    solution = await solver.solve(challenge)
                    
                    logger.info(f"✅ Captcha solved via {solution.solver_method}")
                    return solution
                    
                except CaptchaError as e:
                    logger.warning(f"⚠️ Solver {solver.__class__.__name__} failed: {e}")
                    continue
        
        raise CaptchaError("All captcha solvers failed")
    
    def detect_captcha(self, response_data: dict) -> Optional[CaptchaChallenge]:
        """Detect captcha in API response"""
        
        # Check various captcha response patterns
        if 'captcha' in str(response_data).lower():
            # General case
            return CaptchaChallenge(
                captcha_type='unknown',
                site_url='https://stickerdom.store',
                additional_data=response_data
            )
        
        # reCAPTCHA
        if 'recaptcha' in str(response_data).lower() or 'g-recaptcha' in str(response_data):
            return CaptchaChallenge(
                captcha_type='recaptcha_v2',
                site_key=response_data.get('site_key'),
                site_url='https://stickerdom.store'
            )
        
        # hCaptcha
        if 'hcaptcha' in str(response_data).lower():
            return CaptchaChallenge(
                captcha_type='hcaptcha',
                site_key=response_data.get('site_key'),
                site_url='https://stickerdom.store'
            )
        
        return None 