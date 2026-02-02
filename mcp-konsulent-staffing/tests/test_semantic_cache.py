from __future__ import annotations

from app.semantic_cache import cosine_similarity, hash_vector, pack_vector, unpack_vector


def test_hash_vector_similarity_is_higher_for_similar_texts():
    a = "Python konsulent 50% tilgjengelighet"
    a2 = "Python konsulent 55% tilgjengelighet"
    b = "Java konsulent 10% tilgjengelighet"

    va, na = hash_vector(a)
    va2, na2 = hash_vector(a2)
    vb, nb = hash_vector(b)

    sim_a = cosine_similarity(va, na, va2, na2)
    sim_b = cosine_similarity(va, na, vb, nb)

    assert sim_a > sim_b


def test_pack_unpack_roundtrip():
    vec, _n = hash_vector("hello world")
    b64 = pack_vector(vec)
    vec2 = unpack_vector(b64, dims=len(vec))
    assert vec2 == vec
