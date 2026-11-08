"""Atomic local storage. Files are user-editable data, not signed code plugins."""
import json
import logging
import os
from pathlib import Path
import tempfile

from .schema import valid_profile

MAX_PROFILE_BYTES = 16384
MAX_PROFILES = 64


def profile_directory():
    base = Path(os.environ['LOCALAPPDATA']) if os.environ.get('LOCALAPPDATA') else Path.home() / 'AppData' / 'Local'
    return base / 'MouseBatteryTray' / 'ProtocolProfiles'


def save_profile(profile):
    if not valid_profile(profile):
        raise ValueError('Only a supported binding with capture evidence and three matching live samples can be saved.')
    content = json.dumps(profile, indent=2, ensure_ascii=False).encode('utf-8')
    if len(content) > MAX_PROFILE_BYTES:
        raise ValueError('Profile exceeds the size limit.')
    folder = profile_directory()
    folder.mkdir(parents=True, exist_ok=True)
    destination = folder / f"{profile['vid']:04x}-{profile['pid']:04x}.json"
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=folder, prefix='.profile-', suffix='.tmp', delete=False) as output:
            temporary = Path(output.name)
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return destination


def load_profiles():
    profiles = []
    try:
        files = sorted(profile_directory().glob('*.json'))[:MAX_PROFILES]
    except OSError:
        return profiles
    seen = set()
    for path in files:
        try:
            if path.is_symlink() or path.stat().st_size > MAX_PROFILE_BYTES:
                continue
            profile = json.loads(path.read_text(encoding='utf-8'))
            if not valid_profile(profile):
                raise ValueError('unsupported or unvalidated profile')
            key = profile['vid'], profile['pid']
            if key not in seen:
                profiles.append(profile)
                seen.add(key)
        except (OSError, ValueError, TypeError, KeyError):
            logging.getLogger(__name__).warning('Skipped invalid local protocol profile: %s', path.name)
    return profiles
