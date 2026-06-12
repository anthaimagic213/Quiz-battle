"""
Search endpoints - semantic search theo PHASE2_SETUP.md.

GET /api/v1/search/quizzes?q=...&top_k=10
GET /api/v1/search/questions?q=...&top_k=10
"""

from fastapi import APIRouter, Depends, Query
from typing import List
from uuid import UUID

from app.api.dependencies import get_current_user
from app.services import search_service

router = APIRouter(prefix="/search", tags=["search"])


@router.get("/quizzes", response_model=List[dict])
def search_quizzes_endpoint(
    q: str = Query(..., min_length=1, description="Câu truy vấn ngôn ngữ tự nhiên"),
    top_k: int = Query(10, ge=1, le=50, description="Số kết quả trả về"),
    current_user: UUID = Depends(get_current_user),
):
    """
    Semantic search trên quiz_embeddings.
    Mặc định filter is_public=true AND is_deleted=false.
    """
    return search_service.search_quizzes(query=q, top_k=top_k)


@router.get("/questions", response_model=List[dict])
def search_questions_endpoint(
    q: str = Query(..., min_length=1, description="Câu truy vấn ngôn ngữ tự nhiên"),
    top_k: int = Query(10, ge=1, le=50, description="Số kết quả trả về"),
    current_user: UUID = Depends(get_current_user),
):
    """
    Semantic search trên question_embeddings.
    Mặc định filter is_public=true AND is_deleted=false.
    """
    return search_service.search_questions(query=q, top_k=top_k)
