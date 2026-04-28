from src.domain.entities import Entity
from src.domain.repository_port import RepositoryPort

class UseCase:
    def __init__(self, repo: RepositoryPort):
        self.repo = repo
    
    def execute(self, entity: Entity):
        return entity
