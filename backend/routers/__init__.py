from backend.routers.auth import router as AuthRouter
from backend.routers.collections import router as CollectionsRouter
from backend.routers.delivery import router as DeliveryRouter
from backend.routers.exports import router as ExportsRouter
from backend.routers.payments import router as PaymentsRouter
from backend.routers.products import router as ProductsRouter
from backend.routers.promo_codes import router as PromoCodesRouter
from backend.routers.settings import router as SettingsRouter
from backend.routers.uploads import router as UploadsRouter
from backend.routers.visits import router as VisitsRouter

__all__ = [
    "AuthRouter",
    "CollectionsRouter",
    "DeliveryRouter",
    "ExportsRouter",
    "PaymentsRouter",
    "ProductsRouter",
    "PromoCodesRouter",
    "SettingsRouter",
    "UploadsRouter",
    "VisitsRouter",
]
