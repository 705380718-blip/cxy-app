from __future__ import annotations

from ..config import Settings
from ..mac_probe import MacEnvironmentProbe, MacListener
from ..service import OrganizerService
from .windows import WindowsEnvironmentProbe, WindowsListener


def create_platform_services(
    settings: Settings, service: OrganizerService
) -> tuple[MacEnvironmentProbe | WindowsEnvironmentProbe, MacListener | WindowsListener]:
    if settings.runtime_platform == "windows":
        return WindowsEnvironmentProbe(settings), WindowsListener(settings, service)
    return MacEnvironmentProbe(settings), MacListener(settings, service)
