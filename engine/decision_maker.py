# engine/decision_maker.py - resolves final outcome from stage results
import json
from datetime import datetime


class DecisionMaker:
    @staticmethod
    def make_decision(stage_results: dict, workflow_config: dict) -> dict:
        outcomes = []
        has_failure = False

        for stage_name, result in stage_results.items():
            if result.get('error'):
                has_failure = True
                continue
            if result.get('outcome'):
                outcomes.append({'stage': stage_name, 'outcome': result['outcome']})

        # priority: REJECTED > MANUAL_REVIEW > APPROVED
        if has_failure:
            final = 'FAILED'
        elif any(o['outcome'] == 'REJECTED' for o in outcomes):
            final = 'REJECTED'
        elif any(o['outcome'] == 'MANUAL_REVIEW' for o in outcomes):
            final = 'MANUAL_REVIEW'
        elif any(o['outcome'] == 'APPROVED' for o in outcomes):
            final = 'APPROVED'
        else:
            final = 'APPROVED'

        explanation = DecisionMaker._build_explanation(workflow_config, stage_results, outcomes, final)
        return {
            'outcome': final,
            'explanation': explanation,
            'stageOutcomes': outcomes,
            'decidedAt': datetime.utcnow().isoformat() + 'Z',
        }

    @staticmethod
    def _build_explanation(config: dict, stage_results: dict, outcomes: list, final: str) -> str:
        lines = [
            f"=== Decision Report for Workflow: {config.get('name', 'Unknown')} ===",
            f"Final Outcome: {final}",
            f"Timestamp: {datetime.utcnow().isoformat()}Z",
            '',
            '--- Stage-by-Stage Analysis ---',
        ]

        for stage in config.get('stages', []):
            result = stage_results.get(stage['name'])
            if not result:
                lines.append(f"\n[{stage['name']}] ({stage['type']}): SKIPPED")
                continue

            lines.append(f"\n[{stage['name']}] ({stage['type']}):")

            if result.get('error'):
                lines.append(f"  Status: ERROR")
                lines.append(f"  Error: {result['error']}")
                continue

            if result.get('results') and isinstance(result['results'], list):
                if result.get('outcome'):
                    lines.append(f"  Result: {result['outcome']}")
                lines.append(f"  Rules checked: {len(result['results'])}")
                for r in result['results']:
                    lines.append(f"    {r.get('reasoning', '')}")
            elif result.get('externalResult'):
                ext = result['externalResult']
                lines.append(f"  Service: {ext.get('service')}")
                lines.append(f"  Status: {'Successful' if ext.get('success') else 'Failed'}")
                if ext.get('data'):
                    lines.append(f"  Response: {json.dumps(ext['data'])}")
            elif result.get('valid') is not None:
                lines.append(f"  Status: {'All checks passed' if result['valid'] else 'Validation failed'}")
                for err in result.get('errors', []):
                    lines.append(f"    ✗ {err}")
            else:
                lines.append(f"  Status: OK")

        lines.append('')
        lines.append('--- Final Decision ---')
        lines.append(f'Outcome: {final}')
        if final == 'REJECTED':
            rejections = [o['stage'] for o in outcomes if o['outcome'] == 'REJECTED']
            lines.append(f"Rejection reasons: {', '.join(rejections)}")
        elif final == 'MANUAL_REVIEW':
            lines.append('Reason: One or more stages flagged for manual review.')

        return '\n'.join(lines)
