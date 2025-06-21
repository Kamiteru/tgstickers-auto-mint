#!/usr/bin/env python3
"""
Endpoint Manager
Fast endpoint validation and fallback system for production use
"""

import asyncio
import json
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from enum import Enum

from utils.logger import logger
from config import settings


class EndpointStatus(Enum):
    WORKING = "working"
    FAILED = "failed"
    UNKNOWN = "unknown"
    TESTING = "testing"


@dataclass
class EndpointInfo:
    """Endpoint information with status tracking"""
    url: str
    method: str
    operation_type: str
    parameters: Dict[str, Any]
    status: EndpointStatus
    last_tested: datetime
    success_rate: float = 1.0
    avg_response_time: float = 0.0
    failure_count: int = 0
    priority: int = 1  # Lower number = higher priority


class EndpointManager:
    """Fast endpoint validation and management"""
    
    def __init__(self, api_client=None):
        self.api_client = api_client
        self.endpoints = self._load_default_endpoints()
        self.endpoint_stats = {}
        self.last_discovery_check = None
        
    def _load_default_endpoints(self) -> Dict[str, List[EndpointInfo]]:
        """Load default known working endpoints"""
        return {
            'purchase_ton': [
                EndpointInfo(
                    url='/api/v1/shop/buy/crypto',
                    method='POST',
                    operation_type='purchase_ton',
                    parameters={'collection': 0, 'character': 0, 'currency': 'TON', 'count': 5},
                    status=EndpointStatus.WORKING,
                    last_tested=datetime.now(),
                    priority=1
                ),
                EndpointInfo(
                    url='/api/v1/shop/purchase/crypto',
                    method='POST',
                    operation_type='purchase_ton',
                    parameters={'collection': 0, 'character': 0, 'currency': 'TON'},
                    status=EndpointStatus.UNKNOWN,
                    last_tested=datetime.now() - timedelta(days=1),
                    priority=2
                ),
                EndpointInfo(
                    url='/api/v1/crypto/buy',
                    method='POST',
                    operation_type='purchase_ton',
                    parameters={'collection_id': 0, 'character_id': 0, 'token': 'TON'},
                    status=EndpointStatus.UNKNOWN,
                    last_tested=datetime.now() - timedelta(days=1),
                    priority=3
                )
            ],
            'purchase_stars': [
                EndpointInfo(
                    url='/api/v1/shop/buy',
                    method='POST',
                    operation_type='purchase_stars',
                    parameters={'collection': 0, 'character': 0},
                    status=EndpointStatus.WORKING,
                    last_tested=datetime.now(),
                    priority=1
                ),
                EndpointInfo(
                    url='/api/v1/shop/purchase',
                    method='POST',
                    operation_type='purchase_stars',
                    parameters={'collection': 0, 'character': 0, 'payment_method': 'STARS'},
                    status=EndpointStatus.UNKNOWN,
                    last_tested=datetime.now() - timedelta(days=1),
                    priority=2
                ),
                EndpointInfo(
                    url='/api/v1/stars/buy',
                    method='POST',
                    operation_type='purchase_stars',
                    parameters={'collection_id': 0, 'character_id': 0},
                    status=EndpointStatus.UNKNOWN,
                    last_tested=datetime.now() - timedelta(days=1),
                    priority=3
                )
            ],
            'collection': [
                EndpointInfo(
                    url='/api/v1/collection/{id}',
                    method='GET',
                    operation_type='collection',
                    parameters={},
                    status=EndpointStatus.WORKING,
                    last_tested=datetime.now(),
                    priority=1
                ),
                EndpointInfo(
                    url='/api/v1/collections/{id}',
                    method='GET',
                    operation_type='collection',
                    parameters={},
                    status=EndpointStatus.UNKNOWN,
                    last_tested=datetime.now() - timedelta(days=1),
                    priority=2
                ),
                EndpointInfo(
                    url='/api/v1/shop/collection/{id}',
                    method='GET',
                    operation_type='collection',
                    parameters={},
                    status=EndpointStatus.UNKNOWN,
                    last_tested=datetime.now() - timedelta(days=1),
                    priority=3
                )
            ],
            'price': [
                EndpointInfo(
                    url='/api/v1/shop/price/crypto',
                    method='GET',
                    operation_type='price',
                    parameters={'collection': 0, 'character': 0},
                    status=EndpointStatus.WORKING,
                    last_tested=datetime.now(),
                    priority=1
                ),
                EndpointInfo(
                    url='/api/v1/price/crypto',
                    method='GET',
                    operation_type='price',
                    parameters={'collection_id': 0, 'character_id': 0},
                    status=EndpointStatus.UNKNOWN,
                    last_tested=datetime.now() - timedelta(days=1),
                    priority=2
                )
            ]
        }
    
    async def get_best_endpoint(self, operation_type: str) -> Optional[EndpointInfo]:
        """Get the best working endpoint for operation type"""
        if operation_type not in self.endpoints:
            logger.error(f"Unknown operation type: {operation_type}")
            return None
        
        # Sort by priority and status
        candidates = sorted(
            self.endpoints[operation_type],
            key=lambda x: (x.priority, x.status != EndpointStatus.WORKING, -x.success_rate)
        )
        
        # Return first working endpoint
        for endpoint in candidates:
            if endpoint.status == EndpointStatus.WORKING:
                return endpoint
        
        # If no working endpoints, try to validate the best unknown one
        for endpoint in candidates:
            if endpoint.status == EndpointStatus.UNKNOWN:
                if await self._quick_validate_endpoint(endpoint, operation_type):
                    return endpoint
        
        # Last resort - return the highest priority endpoint even if failed
        return candidates[0] if candidates else None
    
    async def _quick_validate_endpoint(self, endpoint: EndpointInfo, operation_type: str) -> bool:
        """Quick validation of endpoint (HEAD/OPTIONS request)"""
        if not self.api_client:
            return False
            
        try:
            start_time = time.time()
            
            # Build full URL
            full_url = f"{self.api_client.api_base}{endpoint.url}"
            
            # For template URLs, use test values
            if '{id}' in full_url:
                full_url = full_url.replace('{id}', '19')  # Test collection ID
            
            # Quick HEAD request to check if endpoint exists
            response = await self.api_client._make_request_raw(
                'HEAD' if endpoint.method == 'GET' else 'OPTIONS',
                full_url,
                timeout=2.0  # Very quick timeout
            )
            
            response_time = time.time() - start_time
            
            # Update endpoint stats
            if response.status_code in [200, 405]:  # 405 = Method not allowed but endpoint exists
                endpoint.status = EndpointStatus.WORKING
                endpoint.success_rate = min(1.0, endpoint.success_rate + 0.1)
                endpoint.failure_count = 0
                logger.debug(f"Endpoint {endpoint.url} validated successfully ({response_time:.2f}s)")
                return True
            else:
                endpoint.status = EndpointStatus.FAILED
                endpoint.success_rate = max(0.0, endpoint.success_rate - 0.2)
                endpoint.failure_count += 1
                logger.debug(f"Endpoint {endpoint.url} validation failed: {response.status_code}")
                return False
                
        except Exception as e:
            endpoint.status = EndpointStatus.FAILED
            endpoint.success_rate = max(0.0, endpoint.success_rate - 0.3)
            endpoint.failure_count += 1
            logger.debug(f"Endpoint {endpoint.url} validation error: {e}")
            return False
        finally:
            endpoint.last_tested = datetime.now()
    
    async def validate_all_endpoints(self, max_time_budget: float = 2.0) -> Dict[str, int]:
        """Validate all endpoints with time budget (for startup)"""
        logger.info(f"Validating all endpoints with {max_time_budget}s budget...")
        start_time = time.time()
        results = {}
        
        for operation_type, endpoint_list in self.endpoints.items():
            working_count = 0
            
            for endpoint in endpoint_list:
                # Check time budget
                if time.time() - start_time > max_time_budget:
                    logger.warning("Endpoint validation stopped due to time budget")
                    break
                
                if await self._quick_validate_endpoint(endpoint, operation_type):
                    working_count += 1
            
            results[operation_type] = working_count
            logger.info(f"{operation_type}: {working_count}/{len(endpoint_list)} endpoints working")
        
        total_time = time.time() - start_time
        logger.info(f"Endpoint validation completed in {total_time:.2f}s")
        return results
    
    def mark_endpoint_failed(self, operation_type: str, url: str, error_details: str = ""):
        """Mark an endpoint as failed based on actual usage"""
        if operation_type not in self.endpoints:
            return
        
        for endpoint in self.endpoints[operation_type]:
            if endpoint.url == url:
                endpoint.status = EndpointStatus.FAILED
                endpoint.failure_count += 1
                endpoint.success_rate = max(0.0, endpoint.success_rate - 0.1)
                endpoint.last_tested = datetime.now()
                
                logger.warning(f"Marked endpoint {url} as failed: {error_details}")
                
                # If this was our primary endpoint, log critical warning
                if endpoint.priority == 1:
                    logger.error(f"PRIMARY endpoint {url} failed! Will use fallback.")
                
                break
    
    def mark_endpoint_success(self, operation_type: str, url: str, response_time: float = 0.0):
        """Mark an endpoint as successful based on actual usage"""
        if operation_type not in self.endpoints:
            return
        
        for endpoint in self.endpoints[operation_type]:
            if endpoint.url == url:
                endpoint.status = EndpointStatus.WORKING
                endpoint.failure_count = 0
                endpoint.success_rate = min(1.0, endpoint.success_rate + 0.05)
                endpoint.last_tested = datetime.now()
                
                if response_time > 0:
                    # Update rolling average response time
                    if endpoint.avg_response_time == 0:
                        endpoint.avg_response_time = response_time
                    else:
                        endpoint.avg_response_time = (endpoint.avg_response_time * 0.8) + (response_time * 0.2)
                
                logger.debug(f"Marked endpoint {url} as successful ({response_time:.2f}s)")
                break
    
    def get_endpoint_stats(self) -> Dict[str, Any]:
        """Get statistics about endpoint health"""
        stats = {}
        
        for operation_type, endpoint_list in self.endpoints.items():
            working = sum(1 for e in endpoint_list if e.status == EndpointStatus.WORKING)
            failed = sum(1 for e in endpoint_list if e.status == EndpointStatus.FAILED)
            unknown = sum(1 for e in endpoint_list if e.status == EndpointStatus.UNKNOWN)
            
            avg_success_rate = sum(e.success_rate for e in endpoint_list) / len(endpoint_list)
            avg_response_time = sum(e.avg_response_time for e in endpoint_list if e.avg_response_time > 0)
            avg_response_time = avg_response_time / max(1, len([e for e in endpoint_list if e.avg_response_time > 0]))
            
            stats[operation_type] = {
                'total': len(endpoint_list),
                'working': working,
                'failed': failed,
                'unknown': unknown,
                'avg_success_rate': avg_success_rate,
                'avg_response_time': avg_response_time,
                'health_score': (working / len(endpoint_list)) * avg_success_rate
            }
        
        return stats
    
    def update_from_discovery(self, discovered_endpoints: Dict[str, Any]):
        """Update endpoint list from discovery results"""
        logger.info("Updating endpoints from discovery results...")
        
        for endpoint_name, discovery_data in discovered_endpoints.items():
            # Parse operation type from endpoint name
            if 'purchase_ton' in endpoint_name or 'crypto' in endpoint_name:
                operation_type = 'purchase_ton'
            elif 'purchase_stars' in endpoint_name or ('purchase' in endpoint_name and 'crypto' not in endpoint_name):
                operation_type = 'purchase_stars'
            elif 'collection' in endpoint_name:
                operation_type = 'collection'
            elif 'price' in endpoint_name:
                operation_type = 'price'
            else:
                continue
            
            # Check if this endpoint is already known
            existing = False
            for endpoint in self.endpoints.get(operation_type, []):
                if endpoint.url == discovery_data.url:
                    # Update existing endpoint
                    endpoint.status = EndpointStatus.WORKING
                    endpoint.success_rate = 1.0
                    endpoint.failure_count = 0
                    endpoint.last_tested = datetime.now()
                    existing = True
                    break
            
            # Add new endpoint if not known
            if not existing and operation_type in self.endpoints:
                new_endpoint = EndpointInfo(
                    url=discovery_data.url,
                    method=discovery_data.method,
                    operation_type=operation_type,
                    parameters=discovery_data.parameters,
                    status=EndpointStatus.WORKING,
                    last_tested=datetime.now(),
                    priority=len(self.endpoints[operation_type]) + 1  # Lower priority for new endpoints
                )
                self.endpoints[operation_type].append(new_endpoint)
                logger.info(f"Added new endpoint: {discovery_data.url}")
        
        # Re-sort endpoints by priority
        for operation_type in self.endpoints:
            self.endpoints[operation_type].sort(key=lambda x: x.priority)
    
    def should_trigger_discovery(self) -> bool:
        """Check if we should trigger endpoint discovery"""
        # Check if too many endpoints are failing
        stats = self.get_endpoint_stats()
        
        for operation_type, stat in stats.items():
            health_score = stat['health_score']
            if health_score < 0.5:  # Less than 50% health
                logger.warning(f"Low health score for {operation_type}: {health_score:.2f}")
                return True
        
        # Check if it's been too long since last discovery
        if self.last_discovery_check:
            time_since_last = datetime.now() - self.last_discovery_check
            if time_since_last > timedelta(hours=24):  # Once per day
                return True
        else:
            return True  # Never checked
        
        return False
    
    async def emergency_endpoint_discovery(self):
        """Trigger emergency endpoint discovery"""
        logger.warning("Triggering emergency endpoint discovery...")
        
        try:
            from .endpoint_discovery import EndpointDiscovery
            discovery = EndpointDiscovery()
            
            # Try to load from cache first
            cached = await discovery.load_cached_endpoints()
            if cached:
                logger.info("Using cached discovery results for emergency")
                self.update_from_discovery(cached)
            else:
                # Run full discovery (this will take time but it's emergency)
                logger.warning("Running full discovery in emergency mode...")
                discovered = await discovery.discover_endpoints()
                self.update_from_discovery(discovered)
            
            self.last_discovery_check = datetime.now()
            
        except Exception as e:
            logger.error(f"Emergency endpoint discovery failed: {e}")
    
    def save_state(self):
        """Save current endpoint state to cache"""
        try:
            state_data = {
                'timestamp': datetime.now().isoformat(),
                'endpoints': {}
            }
            
            for operation_type, endpoint_list in self.endpoints.items():
                state_data['endpoints'][operation_type] = [
                    {
                        'url': e.url,
                        'method': e.method,
                        'operation_type': e.operation_type,
                        'parameters': e.parameters,
                        'status': e.status.value,
                        'last_tested': e.last_tested.isoformat(),
                        'success_rate': e.success_rate,
                        'avg_response_time': e.avg_response_time,
                        'failure_count': e.failure_count,
                        'priority': e.priority
                    } for e in endpoint_list
                ]
            
            import os
            os.makedirs('data', exist_ok=True)
            with open('data/endpoint_manager_state.json', 'w') as f:
                json.dump(state_data, f, indent=2)
            
            logger.debug("Endpoint manager state saved")
            
        except Exception as e:
            logger.error(f"Failed to save endpoint state: {e}")
    
    def load_state(self):
        """Load endpoint state from cache"""
        try:
            with open('data/endpoint_manager_state.json', 'r') as f:
                state_data = json.load(f)
            
            # Check if state is recent enough
            state_time = datetime.fromisoformat(state_data['timestamp'])
            if datetime.now() - state_time > timedelta(hours=6):
                logger.info("Endpoint state is too old, using defaults")
                return
            
            # Load endpoints
            for operation_type, endpoint_data_list in state_data['endpoints'].items():
                if operation_type in self.endpoints:
                    loaded_endpoints = []
                    for data in endpoint_data_list:
                        endpoint = EndpointInfo(
                            url=data['url'],
                            method=data['method'],
                            operation_type=data['operation_type'],
                            parameters=data['parameters'],
                            status=EndpointStatus(data['status']),
                            last_tested=datetime.fromisoformat(data['last_tested']),
                            success_rate=data['success_rate'],
                            avg_response_time=data['avg_response_time'],
                            failure_count=data['failure_count'],
                            priority=data['priority']
                        )
                        loaded_endpoints.append(endpoint)
                    
                    self.endpoints[operation_type] = loaded_endpoints
            
            logger.info("Endpoint manager state loaded from cache")
            
        except FileNotFoundError:
            logger.info("No endpoint state cache found, using defaults")
        except Exception as e:
            logger.warning(f"Failed to load endpoint state: {e}")


# Global endpoint manager instance
endpoint_manager = None

def get_endpoint_manager(api_client=None):
    """Get global endpoint manager instance"""
    global endpoint_manager
    if endpoint_manager is None:
        endpoint_manager = EndpointManager(api_client)
        endpoint_manager.load_state()
    return endpoint_manager 