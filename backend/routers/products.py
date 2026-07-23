from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.schemas.product import ProductCreate, ProductResponse
from backend.services.auth_service import get_current_admin
from backend.services.product_service import CollectionNotFoundError, ProductService

router = APIRouter(prefix="/api/products", tags=["products"])

DbDep = Annotated[AsyncSession, Depends(get_db)]
# Навешивается на изменяющие эндпоинты — пускает только админов
admin_only = [Depends(get_current_admin)]


@router.get("/", response_model=list[ProductResponse])
async def list_products(db: DbDep):
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


@router.post("/", response_model=ProductResponse, status_code=status.HTTP_201_CREATED, dependencies=admin_only)
async def create_product(data: ProductCreate, db: DbDep):
    try:
        return await ProductService(db).create(data)
    except CollectionNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.put("/{product_id}", response_model=ProductResponse, dependencies=admin_only)
async def update_product(product_id: int, data: ProductCreate, db: DbDep):
    try:
        product = await ProductService(db).update(product_id, data)
    except CollectionNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    return product


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=admin_only)
async def delete_product(product_id: int, db: DbDep):
    deleted = await ProductService(db).delete(product_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
