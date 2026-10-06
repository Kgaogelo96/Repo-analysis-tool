"""Repository lifecycle endpoints: ingestion (zip/URL), listing, authors, merges."""
from fastapi import APIRouter

router = APIRouter(prefix="/api/repo", tags=["repo"])
