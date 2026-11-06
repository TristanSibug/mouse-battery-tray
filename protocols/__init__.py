from .beken import BekenProtocol
from .compx import CompxProtocol
from .wlmouse import WLMouseProtocol
from .razer import RazerProtocol
from .rakk import RakkProtocol

def get_all_handlers():
    return [
        RakkProtocol(),
        BekenProtocol(),
        CompxProtocol(),
        WLMouseProtocol(),
        RazerProtocol()
    ]
