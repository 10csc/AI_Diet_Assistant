"""
向量嵌入模块 —— ChromaDB 集合管理、向量查询与 embedding 函数。

依赖于 knowledge_rules 模块的常量与工具函数。
"""

import hashlib
import math
import os
from typing import Any

from .knowledge_rules import (
    KB_VERSION,
    CHROMA_COLLECTION_NAME,
    _clean_cell,
    _tokenize,
)

# 可选依赖
try:
    import chromadb
except ImportError:  # pragma: no cover - 依赖缺失时在运行期给出明确提示
    chromadb = None

try:
    from sentence_transformers import SentenceTransformer
except ImportError:  # pragma: no cover - 依赖缺失时自动回退到本地哈希向量
    SentenceTransformer = None  # type: ignore

try:
    from huggingface_hub import snapshot_download
except ImportError:  # pragma: no cover - 未安装时不影响回退逻辑
    snapshot_download = None  # type: ignore

# ============================================================
# Embedding 配置
# ============================================================

HASH_EMBED_DIM = 256
SEMANTIC_MODEL_NAME = os.getenv("AI_DIET_EMBED_MODEL", "BAAI/bge-small-zh-v1.5")
SEMANTIC_MODEL_DEVICE = os.getenv("AI_DIET_EMBED_DEVICE", "cpu")
SEMANTIC_MODEL_PATH = os.getenv("AI_DIET_EMBED_MODEL_PATH", "").strip()
ALLOW_REMOTE_MODEL_DOWNLOAD = os.getenv("AI_DIET_EMBED_ALLOW_DOWNLOAD", "0").strip() == "1"


# ============================================================
# Embedding 函数实现
# ============================================================

def _embed_text_hash(text: str) -> list[float]:
    """基于哈希的快速文本向量化（回退方案）。"""
    vector = [0.0] * HASH_EMBED_DIM
    tokens = _tokenize(text)
    if not tokens:
        return vector
    for token in tokens:
        digest = hashlib.md5(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:2], "big") % HASH_EMBED_DIM
        sign = 1.0 if digest[2] % 2 == 0 else -1.0
        weight = 1.0 + (len(token) / 10.0)
        vector[index] += sign * weight
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


class _HashEmbeddingFunction:
    """基于哈希的 embedding 函数（兼容 ChromaDB 接口）。"""

    def __call__(self, input: list[str]) -> list[list[float]]:
        return [_embed_text_hash(text) for text in input]


class _SentenceTransformerEmbeddingFunction:
    """基于 sentence-transformers 的 embedding 函数（含自动回退）。"""

    _model = None
    _backend_name = ""
    _disabled = False

    # ChromaDB 新版本要求 embedding 函数有 name 属性
    @property
    def name(self) -> str:
        return self.__class__.backend_name()

    @classmethod
    def backend_name(cls) -> str:
        """返回当前使用的 embedding 后端名称。"""
        if SentenceTransformer is None or cls._disabled:
            return "hash_fallback"
        model_ref = _semantic_model_reference()
        if _local_semantic_model_available():
            return f"sentence-transformers:{model_ref}"
        if ALLOW_REMOTE_MODEL_DOWNLOAD:
            return f"sentence-transformers:{model_ref}"
        return "hash_fallback"

    @classmethod
    def _get_model(cls):
        """获取或初始化 SentenceTransformer 模型。"""
        if SentenceTransformer is None or cls._disabled:
            raise RuntimeError("未安装 sentence-transformers")
        if not _local_semantic_model_available() and not ALLOW_REMOTE_MODEL_DOWNLOAD:
            cls._disabled = True
            raise RuntimeError("未检测到本地中文 embedding 模型，且未开启远程下载")
        if cls._model is None:
            cls._model = SentenceTransformer(
                _semantic_model_reference(),
                device=SEMANTIC_MODEL_DEVICE,
                local_files_only=not ALLOW_REMOTE_MODEL_DOWNLOAD,
            )
            cls._backend_name = cls.backend_name()
        return cls._model

    def __call__(self, input: list[str]) -> list[list[float]]:
        """将文本列表编码为向量。失败时自动回退到哈希方案。"""
        try:
            model = self._get_model()
            embeddings = model.encode(
                input,
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=False,
            )
            return embeddings.tolist()
        except Exception:
            self.__class__._disabled = True
            return [_embed_text_hash(text) for text in input]


_EMBEDDING_FUNCTION = None


def _get_embedding_function():
    """获取全局 embedding 函数单例。"""
    global _EMBEDDING_FUNCTION
    if _EMBEDDING_FUNCTION is None:
        _EMBEDDING_FUNCTION = _SentenceTransformerEmbeddingFunction()
    return _EMBEDDING_FUNCTION


def _current_embedding_backend() -> str:
    """返回当前 embedding 后端名称。"""
    return _SentenceTransformerEmbeddingFunction.backend_name()


def _semantic_model_reference() -> str:
    """返回语义模型引用路径或名称。"""
    return SEMANTIC_MODEL_PATH if SEMANTIC_MODEL_PATH else SEMANTIC_MODEL_NAME


def _local_semantic_model_available() -> bool:
    """检查本地是否已有语义模型缓存。"""
    model_ref = _semantic_model_reference()
    if not model_ref:
        return False
    if os.path.isdir(model_ref):
        return True
    if snapshot_download is None:
        return False
    try:
        snapshot_download(model_ref, local_files_only=True)
        return True
    except Exception:
        return False


# ============================================================
# ChromaDB 集合管理
# ============================================================

def _ensure_chroma_collection(kb: dict[str, Any]) -> str:
    """确保 ChromaDB 集合存在且与当前知识库版本一致。"""
    if chromadb is None:
        raise RuntimeError("未安装 chromadb，请先执行 `pip install chromadb`")
    embedding_function = _get_embedding_function()
    embedding_backend = _current_embedding_backend()
    os.makedirs(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data", "knowledge_base", "chroma_db"
    ), exist_ok=True)
    # Chroma 目录由调用方确保存在
    _chroma_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data", "knowledge_base", "chroma_db"
    )
    client = chromadb.PersistentClient(path=_chroma_dir)
    needs_rebuild = False
    try:
        collection = client.get_collection(
            name=CHROMA_COLLECTION_NAME,
            embedding_function=embedding_function,
        )
        metadata = collection.metadata or {}
        if (
            collection.count() != len(kb.get("documents", []))
            or metadata.get("embedding_backend") != embedding_backend
            or metadata.get("kb_version") != KB_VERSION
        ):
            needs_rebuild = True
    except Exception:
        needs_rebuild = True

    if needs_rebuild:
        try:
            client.delete_collection(CHROMA_COLLECTION_NAME)
        except Exception:
            pass
        collection = client.create_collection(
            name=CHROMA_COLLECTION_NAME,
            embedding_function=embedding_function,
            metadata={
                "description": "AI Diet Assistant nutrition foods",
                "embedding_backend": embedding_backend,
                "kb_version": KB_VERSION,
            },
        )
        documents = []
        ids = []
        metadatas = []
        for doc in kb.get("documents", []):
            ids.append(doc.get("doc_id", ""))
            documents.append(doc.get("vector_document", doc.get("search_text", "")))
            metadatas.append(_build_chroma_metadata(doc))
        if ids:
            collection.add(ids=ids, documents=documents, metadatas=metadatas)
    return embedding_backend


def _build_chroma_metadata(doc: dict[str, Any]) -> dict[str, Any]:
    """构建 ChromaDB 元数据字典。"""
    return {
        "doc_id": _clean_cell(doc.get("doc_id")),
        "name": _clean_cell(doc.get("name")),
        "image_category": _clean_cell(doc.get("image_category")),
        "image_subcategory": _clean_cell(doc.get("image_subcategory")),
        "source_sheet": _clean_cell(doc.get("source_sheet")),
        "coverage_score": float(doc.get("coverage_score", 0.0)),
        "missing_count": len(doc.get("missing_fields", [])),
        "available_count": len(doc.get("available_fields", [])),
    }


def _query_chroma_candidates(query_text: str, top_n: int) -> list[dict[str, Any]]:
    """查询 ChromaDB 并返回候选文档列表。"""
    if chromadb is None:
        raise RuntimeError("未安装 chromadb，请先执行 `pip install chromadb`")
    _chroma_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data", "knowledge_base", "chroma_db"
    )
    client = chromadb.PersistentClient(path=_chroma_dir)
    collection = client.get_collection(
        name=CHROMA_COLLECTION_NAME,
        embedding_function=_get_embedding_function(),
    )
    result = collection.query(
        query_texts=[query_text],
        n_results=top_n,
        include=["metadatas", "distances"],
    )
    ids = result.get("ids", [[]])[0]
    metadatas = result.get("metadatas", [[]])[0]
    distances = result.get("distances", [[]])[0]
    hits = []
    for index, doc_id in enumerate(ids):
        distance = float(distances[index]) if index < len(distances) and distances[index] is not None else 1.0
        metadata = metadatas[index] if index < len(metadatas) and isinstance(metadatas[index], dict) else {}
        hits.append(
            {
                "doc_id": metadata.get("doc_id") or doc_id,
                "vector_score": round(1 / (1 + max(distance, 0.0)), 4),
            }
        )
    return hits
