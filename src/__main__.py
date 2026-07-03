import sys
from pathlib import Path

# The application imports top-level packages (api, db, graph, ...), so the
# `src/` directory must be on sys.path. `python -m src` only adds the project
# root, so add this package's own directory explicitly before importing the app.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import uvicorn

from api import app

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001, reload=False)
