class RetryPolicy:
    """Retry policy for query execution."""
    
    def __init__(self, max_retries: int = 3):
        self.max_retries = max_retries
    
    def should_retry(self, attempt: int) -> bool:
        return attempt < self.max_retries
