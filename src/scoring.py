"""Season-independent fantasy scoring. BIOCORE field mappings belong in an adapter.

Input metrics MUST describe one robot in one played match. Never pass alliance
points as robot production. Missing metrics are an error, not silently zero.
"""
import math

METRICS = ['auto', 'teleop', 'endgame', 'cycles', 'win', 'fouls']
PRESETS = {
    'standard': {'auto': 1, 'teleop': 1, 'endgame': 1, 'cycles': 0, 'win': 5, 'fouls': -1},
    'half_ppr': {'auto': 1, 'teleop': 1, 'endgame': 1, 'cycles': 0.5, 'win': 5, 'fouls': -1},
    'ppr': {'auto': 1, 'teleop': 1, 'endgame': 1, 'cycles': 1, 'win': 5, 'fouls': -1},
}

def default_rules(preset='standard'):
    return {'version': 'biocore-placeholder-v1', 'preset': preset,
            'aggregation': 'average', 'weights': PRESETS[preset].copy()}

def score_metrics(metrics, rules):
    weights = rules['weights']
    missing = [key for key, weight in weights.items() if weight and key not in metrics]
    if missing:
        raise ValueError('Missing required robot metrics: ' + ', '.join(missing))
    if any(key not in METRICS for key in metrics):
        raise ValueError('Unknown metric; update the season adapter first')
    for key, value in metrics.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError(f'{key} must be a finite, nonnegative number')
    if metrics.get('win', 0) not in (0, 0.5, 1):
        raise ValueError('win must be 0, 0.5 (tie), or 1')
    return round(sum(metrics.get(key, 0) * weight for key, weight in weights.items()), 4)

def calculate_match_points(match_data, team_key):
    """Compatibility entry point: normalized robot metrics only; no alliance / 3 estimate."""
    metrics = (match_data or {}).get('robot_metrics', {}).get(team_key)
    if metrics is None:
        return {'total_points': 0, 'breakdown': {}, 'status': 'AWAITING_ROBOT_DATA'}
    return {'total_points': score_metrics(metrics, default_rules()), 'breakdown': metrics}
