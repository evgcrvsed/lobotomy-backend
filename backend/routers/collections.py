from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.schemas.collection import CollectionResponse
from backend.services.collection_service import CollectionService

router = APIRouter(prefix="/api/collections", tags=["collections"])

DbDep = Annotated[AsyncSession, Depends(get_db)]


@router.get("/", response_model=list[CollectionResponse])
async def list_collections(db: DbDep):
    return await CollectionService(db).list_all()
