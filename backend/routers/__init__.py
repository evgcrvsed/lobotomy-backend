from backend.routers.auth import router as AuthRouter
from backend.routers.collections import router as CollectionsRouter
from backend.routers.payments import router as PaymentsRouter
from backend.routers.products import router as ProductsRouter
from backend.routers.uploads import router as UploadsRouter

__all__ = [
    "AuthRouter",
    "CollectionsRouter",
    "PaymentsRouter",
    "ProductsRouter",
    "UploadsRouter",
]
