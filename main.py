import logging
import ctypes
from pathlib import Path

# Roblox's Win32 coordinates and PIL screenshots must use the same physical
# pixels. Set this before importing Tk or creating any windows.
ctypes.windll.user32.SetProcessDPIAware()

from minebot.ui import App


logging.basicConfig(filename=Path(__file__).with_name("bot.log"), level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s", encoding="utf-8")

if __name__ == "__main__":
    App().run()
