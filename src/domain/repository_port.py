from abc import ABC, abstractmethod

class RepositoryPort(ABC):
    @abstractmethod
    def save(self, data):
        pass
