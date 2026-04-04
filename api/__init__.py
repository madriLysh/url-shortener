from .admin import router as admin_router
from .health import router as health_router
from .routes import router as url_router

__all__ = ["url_router", "admin_router", "health_router"]
