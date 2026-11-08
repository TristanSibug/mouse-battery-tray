from .beken import BekenProtocol
from .compx import CompxProtocol
from .wlmouse import WLMouseProtocol
from .razer import RazerProtocol
from .rakk import RakkProtocol

def get_all_handlers(include_profiles=False):
    handlers = [
        RakkProtocol(),
        BekenProtocol(),
        CompxProtocol(),
        WLMouseProtocol(),
        RazerProtocol()
    ]
    if include_profiles:
        from protocol_profiles.store import load_profiles
        from protocol_profiles.runtime import ProfileProtocol
        handlers = [ProfileProtocol(profile) for profile in load_profiles()] + handlers
    return handlers
