"""
Multi-provider coding agent.

Importing anything under `hermes` loads `.env` first. That ordering used to be
maintained by hand -- every module that read an environment variable at import
time had to `import paths` before anything else, and a missing import made the
setting look ignored with no error to explain why. One call here removes the
requirement entirely.
"""

from dotenv import load_dotenv

load_dotenv()

__version__ = "0.2.0"
