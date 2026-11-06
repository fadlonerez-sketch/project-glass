"""Glass.Recovery -- the watchdog and the 'Restore Windows Desktop' command.

* ``python -m glass.recovery --watch <shell pid>`` (started by the Shell): waits for the Shell to exit. A
  clean exit needs nothing. A crash restores the Windows taskbar immediately (from the state the Shell
  saved *before* changing anything) and restarts the Shell, at most 3 times in 10 minutes.
  It also owns the recovery hotkey (Ctrl+Alt+Shift+R), so recovery works even if the Shell hangs.
* ``python -m glass.recovery --restore``: stop Glass and give the user the standard Windows desktop back.
"""
