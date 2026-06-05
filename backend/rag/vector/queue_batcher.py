import itertools
from typing import Iterator

def batch_generator(generator: Iterator[dict], batch_size: int = 32) -> Iterator[list[dict]]:
    """
    Sub-Module 2.1: Batching the Incoming Chunks
    Actively pulls from the Phase 1 continuous generator stream.
    Only allows precisely `batch_size` chunks to populate RAM at any given time.
    """
    iterator = iter(generator)
    while True:
        # islice consumes the generator exactly up to batch_size and stops.
        batch = list(itertools.islice(iterator, batch_size))
        if not batch:
            break
        yield batch
