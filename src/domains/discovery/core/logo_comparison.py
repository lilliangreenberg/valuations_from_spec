"""Logo comparison using perceptual hashing."""

from __future__ import annotations

import imagehash


def compute_hash_similarity(hash1: str, hash2: str) -> float:
    """Compute similarity between two perceptual hashes.

    Uses Hamming distance. Returns float 0.0-1.0.
    """
    h1 = imagehash.hex_to_hash(hash1)
    h2 = imagehash.hex_to_hash(hash2)
    max_distance = len(h1.hash.flatten())
    hamming_distance = h1 - h2
    if max_distance == 0:
        return 1.0
    return 1.0 - (hamming_distance / max_distance)


def are_logos_similar(hash1: str, hash2: str, threshold: float = 0.85) -> bool:
    """Check if two logos are similar based on their perceptual hashes."""
    return compute_hash_similarity(hash1, hash2) >= threshold
