from __future__ import annotations

import uvicorn

from app.config import Settings
from app.main import create_app


if __name__ == "__main__":
    settings = Settings.from_env()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, proxy_headers=False)
