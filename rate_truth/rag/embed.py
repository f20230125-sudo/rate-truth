"""Optional local query encoder; the HTTP deployment can omit ONNX entirely."""

from functools import lru_cache

from rate_truth.settings import ROOT

MODEL = "BAAI/bge-small-en-v1.5"


@lru_cache(maxsize=1)
def local_encoder():
    from fastembed import TextEmbedding

    return TextEmbedding(
        MODEL, cache_dir=str(ROOT / ".local/fastembed"), local_files_only=True, threads=2
    )


def query_embedding(text):
    return next(local_encoder().query_embed(text))
