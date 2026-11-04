"""Pinned yt-dlp entry point: constrain urllib redirect chains explicitly."""
from yt_dlp import main
from yt_dlp.networking._urllib import RedirectHandler

# This private integration is locked to 2026.10.26 and covered by a contract test.
RedirectHandler.max_redirections = 5
RedirectHandler.max_repeats = 2

if __name__ == "__main__":
    main()
