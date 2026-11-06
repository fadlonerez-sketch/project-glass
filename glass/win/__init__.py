"""Windows integration via documented Win32 / COM / WinRT APIs (ctypes, comtypes, pywinrt).

Rules: no injected code into other processes, no undocumented Explorer internals, no screen capture for
understanding content. Each module degrades to a clear 'unavailable' state when its API is missing.
"""
