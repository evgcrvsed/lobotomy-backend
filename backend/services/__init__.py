from backend.services.auth_service import (
    EmailNotConfiguredError,
    EmailSendError,
    VkAuthError,
    client_ip,
    create_token,
    fetch_vk_user,
    generate_login_code,
    get_current_admin,
    get_current_user,
    get_optional_user,
    hash_login_code,
    send_login_code_email,
)
from backend.services.collection_service import CollectionNameTakenError, CollectionNotEmptyError, CollectionService
from backend.services.image_service import compress_image, needs_compression
from backend.services.order_service import OrderError, OrderService
from backend.services.payment_log_service import PaymentLogService
from backend.services.product_service import CollectionNotFoundError, ProductService
from backend.services.promo_code_service import PromoCodeService, PromoCodeTakenError
from backend.services.slugs import slugify
from backend.services.stats_service import StatsError, StatsService, resolve_period
from backend.services.tinkoff_service import TinkoffError, init_payment, verify_notification
from backend.services.visit_service import VisitService, classify

__all__ = [
    "CollectionNameTakenError",
    "CollectionNotEmptyError",
    "CollectionNotFoundError",
    "CollectionService",
    "EmailNotConfiguredError",
    "EmailSendError",
    "OrderError",
    "OrderService",
    "PaymentLogService",
    "ProductService",
    "PromoCodeService",
    "PromoCodeTakenError",
    "StatsError",
    "StatsService",
    "TinkoffError",
    "VisitService",
    "VkAuthError",
    "classify",
    "client_ip",
    "compress_image",
    "create_token",
    "fetch_vk_user",
    "generate_login_code",
    "get_current_admin",
    "get_current_user",
    "get_optional_user",
    "hash_login_code",
    "init_payment",
    "needs_compression",
    "resolve_period",
    "send_login_code_email",
    "slugify",
    "verify_notification",
]
