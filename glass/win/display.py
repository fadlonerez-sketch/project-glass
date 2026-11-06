"""Built-in display brightness via the documented WMI classes WmiMonitorBrightness / WmiMonitorBrightnessMethods.

External monitors usually don't expose brightness through WMI (they need DDC/CI); for them the UI offers
Display settings instead.
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

_MONIKER = "winmgmts:{impersonationLevel=impersonate}!\\\\.\\root\\WMI"


def _wmi():
    import comtypes.client
    return comtypes.client.CoGetObject(_MONIKER, dynamic=True)


def get_brightness() -> int | None:
    try:
        for obj in _wmi().ExecQuery("SELECT CurrentBrightness FROM WmiMonitorBrightness WHERE Active=TRUE"):
            return int(obj.Properties_("CurrentBrightness").Value)
    except Exception as exc:
        log.debug("brightness unavailable: %s", exc)
    return None


def set_brightness(level: int) -> bool:
    level = max(0, min(100, int(level)))
    try:
        for obj in _wmi().ExecQuery("SELECT * FROM WmiMonitorBrightnessMethods WHERE Active=TRUE"):
            params = obj.Methods_("WmiSetBrightness").InParameters.SpawnInstance_()
            params.Properties_("Timeout").Value = 0
            params.Properties_("Brightness").Value = level
            obj.ExecMethod_("WmiSetBrightness", params)
            return True
    except Exception as exc:
        log.debug("set brightness failed: %s", exc)
    return False
