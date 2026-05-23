"""OmniConvert entry point — run with: python main.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from omniconvert.app import OmniConvertApp

if __name__ == "__main__":
    app = OmniConvertApp()
    app.mainloop()
