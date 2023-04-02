from abc import ABC, abstractmethod
from typing import Optional, Callable, Sequence
from chromadb.types import (
    Topic,
    EmbeddingRecord,
    InsertEmbeddingRecord,
    InsertType,
    ScalarEncoding,
    Vector,
    SeqId,
)
import chromadb.ingest.proto.chroma_pb2 as proto
import pulsar.schema as schema
import array


def encode_vector(vector: Vector, encoding: ScalarEncoding = ScalarEncoding.FLOAT32) -> bytes:
    """Encode a vector into a byte array."""

    if encoding == ScalarEncoding.FLOAT32:
        return array.array("f", vector).tobytes()
    elif encoding == ScalarEncoding.INT32:
        return array.array("i", vector).tobytes()
    else:
        raise ValueError(f"Unsupported encoding: {encoding.value}")


def proto_insert(
    embedding: InsertEmbeddingRecord, encoding: Optional[ScalarEncoding] = None
) -> proto.EmbeddingMessage:
    """Return an Protobuf record for an embedding insert."""

    insert_type = embedding["insert_type"]

    if insert_type == InsertType.ADD_ONLY:
        action_type = proto.ActionType.INSERT
    elif insert_type == InsertType.UPDATE_ONLY:
        action_type = proto.ActionType.UPDATE
    elif insert_type == InsertType.ADD_OR_UPDATE:
        action_type = proto.ActionType.UPSERT
    else:
        raise ValueError(f"Unsupported insert type: {insert_type.value}")

    if encoding is None:
        if isinstance(embedding["embedding"][0], float):
            encoding = ScalarEncoding.FLOAT32
        elif isinstance(embedding["embedding"][0], int):
            encoding = ScalarEncoding.INT32
        else:
            raise ValueError(
                f"Unsupported scalar type for vector: {type(embedding['embedding'][0])}"
            )

    vector = proto.Vector(
        dimension=len(embedding["embedding"]),
        encoding=proto.VectorEncoding.Value(encoding.value),
        vector=encode_vector(embedding["embedding"]),
    )

    return proto.EmbeddingMessage(
        id=embedding["id"],
        type=action_type,
        vector=vector,
        metadata=embedding["metadata"],
    )


def proto_delete(id: str) -> proto.EmbeddingMessage:
    """Return an Protobuf record for an embedding delete."""

    return proto.EmbeddingMessage(id=id, type=proto.ActionType.DELETE)


class Producer(ABC):
    """Interface for writing embeddings to an ingest stream"""

    @abstractmethod
    def create_topic(self, topic: Topic) -> None:
        pass

    @abstractmethod
    def delete_topic(self, topic_name: str) -> None:
        pass

    @abstractmethod
    def submit_embedding(self, topic_name: str, embedding: InsertEmbeddingRecord) -> None:
        """Add an embedding record to the given topic."""
        pass

    @abstractmethod
    def submit_embedding_delete(self, topic_name: str, id: str) -> None:
        """Add an embedding deletion record (soft delete) to the given topic."""
        pass

    @abstractmethod
    def reset(self):
        """Delete all topics and data. For testing only, implementations intended for production
        may throw an exception instead of implementing this method."""
        pass


class Consumer(ABC):
    """Interface for reading embeddings off an ingest stream"""

    @abstractmethod
    def register_consume_fn(
        self,
        topic_name: str,
        consume_fn: Callable[[Sequence[EmbeddingRecord]], bool],
        start: Optional[SeqId] = None,
        end: Optional[SeqId] = None,
    ) -> None:
        """Register a function that will be called to recieve embeddings for a given topic. The given function may be
        called any number of times, with any number of records, and may be called concurrently.

        The function should return True if and only if the embeddings were successfully processed.

        If the function returns False or throws an exception, the function may be called again with the same or
        different records."""