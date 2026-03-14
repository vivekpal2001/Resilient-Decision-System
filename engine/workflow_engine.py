# engine/workflow_engine.py - orchestrates stage execution
import asyncio
import time
from engine.rule_engine import RuleEngine
from engine.decision_maker import DecisionMaker
from external import ExternalServiceSimulator


class WorkflowEngine:
    def __init__(self, config_loader, state_machine, audit_logger):
        self.config_loader = config_loader
        self.state_machine = state_machine
        self.audit = audit_logger
        self.rule_engine = RuleEngine()
        self.external_service = ExternalServiceSimulator()

    async def process_request(self, request_id: str, workflow_id: str, input_data: dict) -> dict:
        config = self.config_loader.get_workflow(workflow_id)
        if not config:
            raise ValueError(f"Workflow not found: {workflow_id}")

        stage_results = {}
        current_state = 'RECEIVED'

        try:
            await self._transition(request_id, current_state, 'VALIDATING', 'Starting input validation')
            current_state = 'VALIDATING'

            validation = self._validate_input(input_data, config.get('inputSchema'))
            stage_results['input_validation'] = validation

            if not validation['valid']:
                await self.audit.log_error(request_id, 'input_validation',
                                           f"Validation failed: {', '.join(validation['errors'])}")
                await self._transition(request_id, current_state, 'FAILED', 'Input validation failed')
                await self._update_request(request_id, 'REJECTED',
                                           f"Validation failed: {', '.join(validation['errors'])}")
                return {'requestId': request_id, 'workflowId': workflow_id,
                        'outcome': 'REJECTED', 'error': validation['errors'], 'stageResults': stage_results}

            await self._transition(request_id, current_state, 'EVALUATING', 'Processing workflow stages')
            current_state = 'EVALUATING'

            for stage in config.get('stages', []):
                start = time.time()
                try:
                    result = await self._execute_stage(request_id, stage, input_data, stage_results)
                    stage_results[stage['name']] = result

                    await self.audit.log(request_id, 'STAGE_COMPLETED',
                                         stage_name=stage['name'],
                                         input_snapshot={'type': stage['type']},
                                         output_snapshot=result,
                                         reasoning=f"Stage {stage['name']} completed: {result.get('outcome', 'OK')}",
                                         duration_ms=int((time.time() - start) * 1000))

                    if result.get('outcome') == 'REJECTED' and stage.get('stopOnReject') is not False:
                        break

                except Exception as e:
                    stage_results[stage['name']] = {'error': str(e)}
                    await self.audit.log_error(request_id, stage['name'], str(e))

                    if stage.get('required') is not False:
                        await self._transition(request_id, current_state, 'FAILED', str(e))
                        current_state = 'FAILED'
                        await self._update_request(request_id, 'FAILED', str(e))
                        return {'requestId': request_id, 'workflowId': workflow_id,
                                'outcome': 'FAILED', 'error': str(e), 'stageResults': stage_results}

            decision = DecisionMaker.make_decision(stage_results, config)

            await self.state_machine.transition(request_id, current_state, 'DECIDED',
                                                 f"Decision: {decision['outcome']}")
            await self.audit.log_decision(request_id, decision['outcome'], decision['explanation'])

            final = 'MANUAL_REVIEW' if decision['outcome'] == 'MANUAL_REVIEW' else 'COMPLETED'
            await self.state_machine.transition(request_id, 'DECIDED', final,
                                                 f"Final outcome: {decision['outcome']}")
            await self._update_request(request_id, decision['outcome'], decision['explanation'])

            return {
                'requestId': request_id,
                'workflowId': workflow_id,
                'outcome': decision['outcome'],
                'explanation': decision['explanation'],
                'stageResults': stage_results,
                'stageOutcomes': decision['stageOutcomes'],
                'decidedAt': decision['decidedAt'],
            }

        except Exception as e:
            if current_state != 'FAILED':
                try:
                    await self._transition(request_id, current_state, 'FAILED', str(e))
                except:
                    pass
            await self.audit.log_error(request_id, 'workflow_engine', str(e))
            raise

    async def _execute_stage(self, request_id, stage, input_data, prev_results):
        stage_type = stage['type']
        if stage_type == 'validation':
            return self._execute_validation(stage, input_data)
        elif stage_type == 'rule_evaluation':
            return await self._execute_rules(request_id, stage, input_data)
        elif stage_type == 'external_call':
            return await self._execute_external(request_id, stage, input_data)
        elif stage_type == 'decision':
            return {'outcome': 'OK', 'type': 'decision_placeholder'}
        elif stage_type == 'conditional':
            return self._execute_conditional(stage, input_data)
        else:
            raise ValueError(f"Unknown stage type: {stage_type}")

    def _execute_validation(self, stage, input_data):
        errors = []
        for rule in stage.get('rules', []):
            if rule.get('type') == 'required':
                val = self._get_nested(input_data, rule['field'])
                if val is None or val == '':
                    errors.append(f"{rule['field']} is required")
            elif rule.get('type') == 'type_check':
                val = self._get_nested(input_data, rule['field'])
                expected = rule.get('expectedType')
                if val is not None and expected == 'number' and not isinstance(val, (int, float)):
                    errors.append(f"{rule['field']} must be a number")
                elif val is not None and expected == 'string' and not isinstance(val, str):
                    errors.append(f"{rule['field']} must be a string")
        return {
            'valid': len(errors) == 0,
            'errors': errors,
            'outcome': 'REJECTED' if errors else None,
            'explanation': f"Validation errors: {', '.join(errors)}" if errors else 'All validations passed',
        }

    async def _execute_rules(self, request_id, stage, input_data):
        result = self.rule_engine.evaluate(stage.get('rules', []), input_data)
        for r in result['results']:
            await self.audit.log_rule_evaluation(request_id, stage['name'], r)
        return result

    async def _execute_external(self, request_id, stage, input_data):
        service = stage['service']
        retry = stage.get('retryPolicy', {})

        # slow mode: used to test crash recovery by delaying external calls
        if input_data.get('_slowMode'):
            delay = input_data['_slowMode'] if isinstance(input_data['_slowMode'], (int, float)) else 30
            print(f"⏳ [SLOW MODE] Waiting {delay}s before '{service}'... Kill server now with Ctrl+C!")
            await asyncio.sleep(delay)

        start = time.time()
        result = await self.external_service.call_with_retry(
            service, input_data,
            max_retries=retry.get('maxRetries', 3),
            backoff_ms=retry.get('backoffMs', 200)
        )
        duration = int((time.time() - start) * 1000)
        await self.audit.log_external_call(request_id, stage['name'], service, result, duration)

        if not result['success']:
            if stage.get('required') is not False:
                raise Exception(f"Service {service} failed after {result.get('attempt')} attempts")
            return {'outcome': None, 'externalResult': result,
                    'explanation': f"Service {service} failed (non-critical)"}

        return {'outcome': None, 'externalResult': result,
                'explanation': f"Service {service} call successful"}

    def _execute_conditional(self, stage, input_data):
        cond = stage.get('condition', {})
        result = self.rule_engine._evaluate_rule(cond, input_data)
        return {
            'outcome': cond.get('thenOutcome') if result['passed'] else cond.get('elseOutcome'),
            'conditionMet': result['passed'],
            'explanation': result['reasoning'],
        }

    def _validate_input(self, data, schema):
        if not schema:
            return {'valid': True, 'errors': []}
        errors = []
        required = schema.get('required', [])
        props = schema.get('properties', {})

        for field in required:
            if field not in data or data[field] is None or data[field] == '':
                errors.append(f"{field} is required")

        for field, rules in props.items():
            if field in data and data[field] is not None:
                val = data[field]
                if rules.get('type') == 'number' and not isinstance(val, (int, float)):
                    errors.append(f"{field} must be a number")
                elif rules.get('type') == 'string' and not isinstance(val, str):
                    errors.append(f"{field} must be a string")
                if rules.get('enum') and val not in rules['enum']:
                    errors.append(f"{field} must be one of {rules['enum']}")

        return {'valid': len(errors) == 0, 'errors': errors}

    async def _transition(self, request_id, from_state, to_state, reason):
        await self.state_machine.transition(request_id, from_state, to_state, reason)
        await self.audit.log_state_change(request_id, from_state, to_state, reason)

    async def _update_request(self, request_id, outcome, explanation):
        await self.state_machine.db.execute(
            "UPDATE requests SET outcome=?, decision_explanation=?, updated_at=datetime('now') WHERE id=?",
            (outcome, explanation, request_id)
        )
        await self.state_machine.db.commit()

    @staticmethod
    def _get_nested(obj, path):
        if not path:
            return None
        for key in path.split('.'):
            if isinstance(obj, dict):
                obj = obj.get(key)
            else:
                return None
        return obj
