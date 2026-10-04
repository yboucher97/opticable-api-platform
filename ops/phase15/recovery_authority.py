"""Pure, deterministic fresh-recovery policy. Never grants authority or calls providers."""
from copy import deepcopy


def reset_conversion_authority(archived=None):
    value = deepcopy(archived) if archived is not None else {'schema': 1, 'destinations': {}, 'validated_families': {}}
    if not isinstance(value, dict) or value.get('schema') != 1 or not isinstance(value.get('destinations'), dict):
        raise ValueError('Invalid archived conversion configuration')
    for destination in value['destinations'].values():
        if not isinstance(destination, dict):
            raise ValueError('Invalid archived conversion destination')
        destination['local_enabled'] = False
        destination['allowed_event_keys'] = []
    # Native destination configuration and validation evidence are capability,
    # not execution authority. A new root-reviewed grant must bind the release,
    # exact event and a fresh expiry after recovery.
    for key in ('release_sha', 'source_sha256', 'eligible_after', 'expires_at'):
        value[key] = None
    value['enabled'] = False
    value['recovery_authority'] = 'RESET TO OFF — REQUIRE OWNER RECONFIRMATION'
    verify_conversion_disabled(value)
    return value


def verify_conversion_disabled(value):
    if (not isinstance(value, dict) or value.get('schema') != 1 or value.get('enabled') is not False
            or not isinstance(value.get('destinations'), dict)
            or any(not isinstance(d, dict) or d.get('local_enabled') is not False
                   or d.get('allowed_event_keys') != [] for d in value['destinations'].values())):
        raise ValueError('Recovered conversion export authority is not closed')
    return {'configured_destinations': len(value['destinations']), 'authorized': False,
            'fresh_recovery_default': 'OFF', 'provider_calls': 0}
