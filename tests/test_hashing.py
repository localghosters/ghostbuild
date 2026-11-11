from __future__ import annotations

import hashlib
import io

from ghostbuild.utils.hashing import EMPTY_SHA256, hash_stream, sha256_bytes, sha256_file

ABC_SHA256 = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_known_vectors():
    assert sha256_bytes(b"abc") == ABC_SHA256
    assert sha256_bytes(b"") == EMPTY_SHA256 == (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )


def test_file_hash_matches_hashlib_across_chunk_boundaries(tmp_path):
    data = b"x" * (3 * 1024 * 1024 + 17)
    path = tmp_path / "big.bin"
    path.write_bytes(data)
    assert sha256_file(path) == hashlib.sha256(data).hexdigest()


def test_hash_stream_keeps_small_content_only():
    digest, size, kept = hash_stream(io.BytesIO(b"abc"), keep_up_to=10)
    assert (digest, size, kept) == (ABC_SHA256, 3, b"abc")
    _, size, kept = hash_stream(io.BytesIO(b"abcdef"), keep_up_to=4)
    assert size == 6 and kept is None
    _, _, kept = hash_stream(io.BytesIO(b"abc"), keep_up_to=0)
    assert kept is None
