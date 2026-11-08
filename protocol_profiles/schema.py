"""Profiles choose fixed code templates; no bytecode, commands, or parser code."""
import re

VARIANTS = {'rakk-v1': {'report08'}, 'beken-v1': {'passive'},
            'compx-v1': {'passive', 'get06', 'query06-report0', 'query06-report6'},
            'razer-v1': {'feature90'}, 'wlmouse-v1': {'feature83'}}
ROOT_KEYS = {'schema_version', 'vid', 'pid', 'name', 'template', 'variant', 'interfaces', 'validation'}
VALIDATION_KEYS = {'capture_sha256', 'capture_matches', 'capture_mismatches', 'live_samples',
                   'reference_percent', 'reference_charging', 'verified_at_utc'}


def integer(value, low, high):
    return type(value) is int and low <= value <= high


def valid_binding(profile):
    if not isinstance(profile, dict) or set(profile) != ROOT_KEYS or type(profile['schema_version']) is not int or profile['schema_version'] != 1:
        return False
    if not integer(profile['vid'], 1, 65535) or not integer(profile['pid'], 0, 65535):
        return False
    if not isinstance(profile['name'], str) or not 0 < len(profile['name'].strip()) <= 80 or not profile['name'].isprintable():
        return False
    template = profile['template']
    if not isinstance(template, str) or template not in VARIANTS or not isinstance(profile['variant'], str) or profile['variant'] not in VARIANTS[template]:
        return False
    interfaces = profile['interfaces']
    roles = {'primary', 'reply'} if template == 'rakk-v1' else {'primary'}
    if not isinstance(interfaces, dict) or set(interfaces) != roles:
        return False
    for selector in interfaces.values():
        if not isinstance(selector, dict) or set(selector) != {'interface_number', 'usage_page', 'usage'}:
            return False
        if not integer(selector['interface_number'], -1, 255) or not integer(selector['usage_page'], 0, 65535) or not integer(selector['usage'], 0, 65535):
            return False
    if template == 'rakk-v1':
        if (interfaces['primary']['usage_page'], interfaces['primary']['usage']) != (0xFF02, 2):
            return False
        if (interfaces['reply']['usage_page'], interfaces['reply']['usage']) != (0xFF01, 0):
            return False
    elif template in ('beken-v1', 'compx-v1'):
        if interfaces['primary']['usage_page'] < 0xFF00 and interfaces['primary']['usage_page'] != 10:
            return False
    elif template == 'wlmouse-v1' and interfaces['primary']['usage_page'] != 0xFFFF:
        return False
    elif template == 'razer-v1':
        selector = interfaces['primary']
        if not (selector['usage_page'] >= 0xFF00 or selector['usage_page'] == 1 and selector['usage'] in (2, 6)):
            return False
    return True


def valid_profile(profile):
    if not valid_binding(profile):
        return False
    proof = profile['validation']
    if not isinstance(proof, dict) or set(proof) != VALIDATION_KEYS:
        return False
    if not isinstance(proof['capture_sha256'], str) or not re.fullmatch('[0-9a-f]{64}', proof['capture_sha256']):
        return False
    if not integer(proof['capture_matches'], 2, 1000000) or not integer(proof['capture_mismatches'], 0, 1000000):
        return False
    if proof['capture_matches'] / (proof['capture_matches'] + proof['capture_mismatches']) < 0.8:
        return False
    if not integer(proof['reference_percent'], 0, 100) or type(proof['reference_charging']) is not bool:
        return False
    if not isinstance(proof['verified_at_utc'], str) or not 10 <= len(proof['verified_at_utc']) <= 40:
        return False
    samples = proof['live_samples']
    return (isinstance(samples, list) and len(samples) == 3 and all(
        isinstance(sample, dict) and set(sample) == {'percent', 'charging'}
        and integer(sample['percent'], 0, 100) and type(sample['charging']) is bool
        and abs(sample['percent'] - proof['reference_percent']) <= 1
        and sample['charging'] == proof['reference_charging'] for sample in samples))
