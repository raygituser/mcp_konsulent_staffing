from __future__ import annotations

import sys
from pathlib import Path


# Allow `import app...` from llm_verktoy_api/app without installing the package.
ROOT = Path(__file__).resolve().parent.parent
LLM_API = ROOT / "llm_verktoy_api"
if str(LLM_API) not in sys.path:
    sys.path.insert(0, str(LLM_API))