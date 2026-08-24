from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.schemas.product import (
    ProductAdminResponse,
    ProductCreate,
    ProductResponse,
    ProductVisibilityUpdate,
)
from backend.services.auth_service import get_current_admin
from backend.services.product_service import CollectionNotFoundError, ProductInOrdersError, ProductService

router = APIRouter(prefix="/api/products", tags=["products"])

DbDep = Annotated[AsyncSession, Depends(get_db)]
# Навешивается на изменяющие эндпоинты — пускает только админов
admin_only = [Depends(get_current_admin)]


@router.get("/", response_model=list[ProductResponse])
async def list_products(db: DbDep):
    """Каталог для витрины. Цвет и вес сюда не попадают — они внутренние."""
    return await ProductService(db).list_all()


# Объявлен раньше "/{product_id}" — иначе слово "admin" уйдёт туда как число
@router.get("/admin", response_model=list[ProductAdminResponse], dependencies=admin_only)
async def list_products_for_admin(db: DbDep):
    """Тот же каталог, но с цветом и весом: их правят в админке и по ним
    собирается выгрузка на отшив."""
    return await ProductService(db).list_all()


# важно: объявлен раньше "/{product_id}", иначе слово "slug" попытается стать числом
@router.get("/slug/{slug}", response_model=ProductResponse)
async def get_product_by_slug(slug: str, db: DbDep):
    product = await ProductService(db).get_by_slug(slug)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    return product


@router.get("/{product_id}", response_model=ProductResponse)
async def get_product(product_id: int, db: DbDep):
    product = await ProductService(db).get_by_id(product_id)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    return product


@router.post("/", response_model=ProductAdminResponse, status_code=status.HTTP_201_CREATED, dependencies=admin_only)
async def create_product(data: ProductCreate, db: DbDep):
    try:
        return await ProductService(db).create(data)
    except CollectionNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.put("/{product_id}", response_model=ProductAdminResponse, dependencies=admin_only)
async def update_product(product_id: int, data: ProductCreate, db: DbDep):
    try:
        product = await ProductService(db).update(product_id, data)
    except CollectionNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    return product


@router.patch("/{product_id}/visibility", response_model=ProductAdminResponse, dependencies=admin_only)
async def set_product_visibility(product_id: int, data: ProductVisibilityUpdate, db: DbDep):
    product = await ProductService(db).set_hidden(product_id, data.is_hidden)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    return product


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=admin_only)
async def delete_product(product_id: int, db: DbDep):
    try:
        deleted = await ProductService(db).delete(product_id)
    except ProductInOrdersError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
