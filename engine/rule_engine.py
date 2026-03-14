# engine/rule_engine.py - evaluates rules against input data
import re
import time
from typing import Any


class RuleEngine:
    # supported operators: >=, <=, >, <, ==, !=, in, not_in, range, regex, exists, not_exists
    OPERATORS = {
        '>=': lambda v, t, _: v >= t,
        '<=': lambda v, t, _: v <= t,
        '>':  lambda v, t, _: v > t,
        '<':  lambda v, t, _: v < t,
        '==': lambda v, t, _: v == t,
        '!=': lambda v, t, _: v != t,
        'in': lambda v, t, _: v in t,
        'not_in': lambda v, t, _: v not in t,
        'range': lambda v, _, r: r.get('min', 0) <= v <= r.get('max', 0),
        'regex': lambda v, t, _: bool(re.search(t, str(v))),
        'exists': lambda v, _, __: v is not None,
        'not_exists': lambda v, _, __: v is None,
    }

    def evaluate(self, rules: list, data: dict) -> dict:
        results = []
        final_outcome = None

        for rule in rules:
            result = self._evaluate_rule(rule, data)
            results.append(result)

            # mandatory rule fails → stop immediately
            if rule.get('mandatory') and not result['passed']:
                final_outcome = rule.get('failOutcome', 'REJECTED')
                break

            if result['passed'] and rule.get('outcome'):
                final_outcome = rule['outcome']

        return {
            'outcome': final_outcome,
            'results': results,
            'explanation': self._build_explanation(results),
            'rulesEvaluated': len(results),
            'rulesPassed': sum(1 for r in results if r['passed']),
            'rulesFailed': sum(1 for r in results if not r['passed']),
        }

    def _evaluate_rule(self, rule: dict, data: dict) -> dict:
        start = time.time()
        name = rule.get('name', rule.get('field', 'unknown'))
        field = rule.get('field', '')
        value = self._get_nested(data, field)
        operator = rule.get('operator', '')

        op_fn = self.OPERATORS.get(operator)
        if not op_fn:
            return {
                'ruleName': name, 'field': field, 'operator': operator,
                'passed': False, 'error': f'Unknown operator: {operator}',
                'reasoning': f"Cannot evaluate: unknown operator '{operator}'",
                'durationMs': int((time.time() - start) * 1000),
            }

        try:
            passed = op_fn(value, rule.get('value'), rule)
        except Exception as e:
            return {
                'ruleName': name, 'field': field, 'operator': operator,
                'passed': False, 'error': str(e),
                'reasoning': f'Error: {e}',
                'durationMs': int((time.time() - start) * 1000),
            }

        return {
            'ruleName': name, 'field': field, 'operator': operator,
            'fieldValue': value, 'expectedValue': rule.get('value'),
            'passed': passed,
            'outcome': rule.get('outcome') if passed else rule.get('failOutcome'),
            'mandatory': rule.get('mandatory', False),
            'reasoning': self._get_reasoning(rule, name, field, value, passed),
            'durationMs': int((time.time() - start) * 1000),
        }

    def _get_reasoning(self, rule: dict, name: str, field: str, value: Any, passed: bool) -> str:
        op = rule.get('operator', '')

        if op == 'range':
            if passed:
                return f"✓ {name}: {field} is {value}, within range {rule.get('min')} to {rule.get('max')}"
            return f"· {name}: {field} is {value}, outside range {rule.get('min')} to {rule.get('max')} — not applicable"

        if op == 'exists':
            return f"✓ {name}: '{field}' is present" if passed else f"✗ {name}: '{field}' is missing"
        if op == 'not_exists':
            return f"✓ {name}: '{field}' absent" if passed else f"✗ {name}: '{field}' should not be present"

        descs = {
            '>=': (f"is {value}, meets minimum of {rule.get('value')}", f"is {value}, below minimum of {rule.get('value')}"),
            '<=': (f"is {value}, within maximum of {rule.get('value')}", f"is {value}, exceeds maximum of {rule.get('value')}"),
            '>':  (f"is {value}, above {rule.get('value')}", f"is {value}, not above {rule.get('value')}"),
            '<':  (f"is {value}, below {rule.get('value')}", f"is {value}, not below {rule.get('value')}"),
            '==': (f'is "{value}", matches "{rule.get("value")}"', f'is "{value}", does not match "{rule.get("value")}"'),
            '!=': (f'is "{value}", different from "{rule.get("value")}" as required', f'is "{value}", matches disallowed value "{rule.get("value")}"'),
            'in': (f'is "{value}", in the allowed list', f'is "{value}", not in the allowed list'),
            'not_in': (f'is "{value}", not in the restricted list', f'is "{value}", in the restricted list'),
            'regex': (f'"{value}" matches pattern', f'"{value}" does not match pattern'),
        }

        desc = descs.get(op, (f"evaluated ({value})", f"evaluated ({value})"))
        if passed:
            outcome_label = f" → {rule['outcome']}" if rule.get('outcome') else ''
            return f"✓ {name}: {field} {desc[0]}{outcome_label}"
        else:
            is_reject = rule.get('outcome') == 'REJECTED' or rule.get('failOutcome') == 'REJECTED'
            suffix = ' — no concern' if is_reject else ' — not applicable'
            return f"{'✓' if is_reject else '·'} {name}: {field} {desc[1]}{suffix}"

    def _build_explanation(self, results: list) -> str:
        lines = [f"  {i+1}. {r['reasoning']}" for i, r in enumerate(results)]
        return f"Rules evaluated: {len(results)}\n" + '\n'.join(lines)

    @staticmethod
    def _get_nested(obj: dict, path: str) -> Any:
        if not path:
            return None
        for key in path.split('.'):
            if isinstance(obj, dict):
                obj = obj.get(key)
            else:
                return None
        return obj
