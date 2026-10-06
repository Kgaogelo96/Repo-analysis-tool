"""Metric query endpoints driving the dashboard (tree, files, charts, authors)."""
from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["metrics"])
