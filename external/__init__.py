# external/__init__.py - simulates external service calls with retry
import asyncio
import random


SERVICES = {
    'credit_bureau': {
        'failureRate': 0.15,
        'latencyMs': 200,
        'response': lambda data: {
            'creditScore': data.get('credit_score', 650),
            'riskLevel': 'LOW' if data.get('credit_score', 650) >= 700 else 'HIGH',
            'delinquencies': 0 if data.get('credit_score', 650) >= 700 else 1,
            'verified': True,
        }
    },
    'document_verification': {
        'failureRate': 0.10,
        'latencyMs': 300,
        'response': lambda data: {
            'documentsValid': True,
            'verificationId': f"VER-{random.randint(10000,99999)}",
        }
    },
    'identity_verification': {
        'failureRate': 0.05,
        'latencyMs': 150,
        'response': lambda data: {
            'identityConfirmed': True,
            'matchScore': round(random.uniform(0.85, 1.0), 2),
        }
    },
    'compliance_check': {
        'failureRate': 0.08,
        'latencyMs': 250,
        'response': lambda data: {
            'sanctionsClean': True,
            'amlClean': True,
            'pepCheck': False,
        }
    },
}


class ExternalServiceSimulator:
    async def call(self, service_name: str, data: dict) -> dict:
        service = SERVICES.get(service_name)
        if not service:
            raise ValueError(f"Unknown service: {service_name}")

        await asyncio.sleep(service['latencyMs'] / 1000)

        if random.random() < service['failureRate']:
            return {'success': False, 'error': f'{service_name} temporarily unavailable', 'service': service_name}

        return {'success': True, 'data': service['response'](data), 'service': service_name}

    async def call_with_retry(self, service_name: str, data: dict,
                               max_retries: int = 3, backoff_ms: int = 200) -> dict:
        for attempt in range(1, max_retries + 1):
            result = await self.call(service_name, data)
            result['attempt'] = attempt

            if result['success']:
                return result

            # exponential backoff between retries
            if attempt < max_retries:
                wait = (backoff_ms / 1000) * (2 ** (attempt - 1))
                await asyncio.sleep(wait)

        return result
