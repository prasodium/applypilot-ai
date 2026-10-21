"""Writes the API's OpenAPI document (no server needed). Used by `npm run gen:api` to generate the typed frontend client."""
import json
import sys
import tempfile
from pathlib import Path

from app.config import Settings
from app.main import create_app

out = Path(sys.argv[1] if len(sys.argv) > 1 else "openapi.json")
with tempfile.TemporaryDirectory() as tmp:
    app = create_app(Settings(database_url=f"sqlite:///{tmp}/x.db", mount_mock_employer=False, _env_file=None), migrate=False)
    out.write_text(json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n")
print(f"wrote {out}")
