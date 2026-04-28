from src.application.use_case import QueryUseCase
from src.infrastructure.repository import Repository


def build_components() -> tuple[QueryUseCase, Repository]:
    return QueryUseCase(), Repository()
