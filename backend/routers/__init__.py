from backend.routers.auth import router as AuthRouter
from backend.routers.collections import router as CollectionsRouter
from backend.routers.delivery import router as DeliveryRouter
from backend.routers.payments import router as PaymentsRouter
from backend.routers.products import router as ProductsRouter
from backend.routers.settings import router as SettingsRouter
from backend.routers.uploads import router as UploadsRouter
from backend.routers.visits import router as VisitsRouter

__all__ = [
    "AuthRouter",
    "CollectionsRouter",
    "DeliveryRouter",
    "PaymentsRouter",
    "ProductsRouter",
    "SettingsRouter",
    "UploadsRouter",
    "VisitsRouter",
]
