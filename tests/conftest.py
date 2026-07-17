import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Bot modules import each other flat ("from config import ..."), so Bot/
# itself must be on sys.path, same as when running Bot/main.py.
sys.path.insert(0, os.path.join(REPO, "Bot"))
sys.path.insert(0, REPO)
