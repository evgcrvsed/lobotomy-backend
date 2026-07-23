from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.schemas.collection import CollectionCreate, CollectionResponse, CollectionUpdate
from backend.services.auth_service import get_current_admin
from backend.services.collection_service import (
    CollectionNameTakenError,
    CollectionNotEmptyError,
    CollectionService,
)

router = APIRouter(prefix="/api/collections", tags=["collections"])

DbDep = Annotated[AsyncSession, Depends(get_db)]
admin_only = [Depends(get_current_admin)]


@router.get("/", response_model=list[CollectionResponse])
async def list_collections(db: DbDep):
    return await CollectionService(db).list_all()


@router.post("/", response_model=CollectionResponse, status_code=status.HTTP_201_CREATED, dependencies=admin_only)
async def create_collection(data: CollectionCreate, db: DbDep):
    try:
        return await CollectionService(db).create(data.name.strip())
    except CollectionNameTakenError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


@router.put("/{collection_id}", response_model=CollectionResponse, dependencies=admin_only)
async def update_collection(collection_id: int, data: CollectionUpdate, db: DbDep):
    try:
        collection = await CollectionService(db).update(collection_id, data.name.strip(), data.image)
    except CollectionNameTakenError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    if collection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")
    return collection


@router.delete("/{collection_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=admin_only)
async def delete_collection(collection_id: int, db: DbDep):
    try:
        deleted = await CollectionService(db).delete(collection_id)
    except CollectionNotEmptyError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")
