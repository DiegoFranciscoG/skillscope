import numpy as np

from indexer.embeddings import build_lsa, decode, encode, quantize_rows

CORPUS = [
    ("a/review", "review pull requests diff code review comments reviewer"),
    ("b/review2", "code review of pull requests and diffs before merge"),
    ("c/tests", "write unit tests pytest coverage flaky tests"),
    ("d/tests2", "unit tests and e2e tests with playwright coverage"),
    ("e/docs", "write readme documentation api docs reference"),
    ("f/docs2", "documentation writer readme changelog docs"),
    ("g/security", "secret scanning gitleaks security secrets audit"),
    ("h/security2", "security audit owasp secrets vulnerabilities"),
]


def test_semantic_neighbours() -> None:
    model = build_lsa(CORPUS)
    assert model.dims == 7  # min(64, docs - 1, terms - 1)
    sims = model.similarities(model.project("necesito revisar pull requests"))
    ranked = [model.ids[i] for i in np.argsort(-sims)]
    assert set(ranked[:2]) == {"a/review", "b/review2"}
    sims = model.similarities(model.project("pruebas unitarias"))
    assert model.ids[int(np.argmax(sims))] in {"c/tests", "d/tests2"}


def test_unknown_query_projects_to_zero() -> None:
    model = build_lsa(CORPUS)
    vector = model.project("cobol mainframe")
    assert not vector.any()
    assert not model.similarities(vector).any()


def test_deterministic_and_binary_roundtrip() -> None:
    first = encode(build_lsa(CORPUS))
    second = encode(build_lsa(CORPUS))
    assert first == second  # fixed seed
    model = build_lsa(CORPUS)
    dims, docs, scales, terms = decode(first)
    assert dims == model.dims
    assert docs.shape == (len(CORPUS), dims)
    assert terms.shape == (len(model.terms), dims)
    restored = docs.astype(np.float64) / 127
    assert np.allclose(restored, model.doc_vectors, atol=0.01)
    restored_terms = terms.astype(np.float64) * scales[:, None]
    assert np.allclose(restored_terms, model.term_vectors, atol=0.01)


def test_quantize_rows_handles_zero_rows() -> None:
    matrix = np.array([[0.5, -1.0], [0.0, 0.0]])
    quantized, scale = quantize_rows(matrix)
    assert quantized.tolist() == [[64, -127], [0, 0]]
    assert scale[1] == 1.0


def test_tiny_corpus_falls_back_without_vectors() -> None:
    model = build_lsa([("only/one", "single document")])
    assert model.dims == 0
    assert not model.project("single").any()
    payload = encode(model)
    assert decode(payload)[0] == 0
