"""Document chunking utilities for RAG ingestion.

Provides strategies for splitting documents into chunks suitable
for embedding and retrieval.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator


@dataclass
class Chunk:
    """A document chunk for indexing."""
    
    content: str
    doc_type: str
    file_path: str | None = None
    source_url: str | None = None
    chunk_index: int = 0


def chunk_diff(
    diff_text: str,
    *,
    pr_url: str | None = None,
    max_chunk_size: int = 2000,
) -> Iterator[Chunk]:
    """Chunk a PR diff into file-level or hunk-level pieces.
    
    Args:
        diff_text: The full diff text.
        pr_url: Optional PR URL for source links.
        max_chunk_size: Maximum characters per chunk.
    
    Yields:
        Chunk objects for each piece.
    """
    current_file = None
    current_content = []
    chunk_index = 0
    
    for line in diff_text.split("\n"):
        # Detect file boundaries
        if line.startswith("diff --git"):
            # Yield previous file's content
            if current_file and current_content:
                content = "\n".join(current_content)
                for sub_chunk in _split_content(content, max_chunk_size):
                    yield Chunk(
                        content=sub_chunk,
                        doc_type="diff",
                        file_path=current_file,
                        source_url=pr_url,
                        chunk_index=chunk_index,
                    )
                    chunk_index += 1
            
            # Parse new file path
            parts = line.split(" ")
            if len(parts) >= 4:
                # Extract "b/path/to/file" format
                b_path = parts[-1]
                if b_path.startswith("b/"):
                    current_file = b_path[2:]
                else:
                    current_file = b_path
            else:
                current_file = "unknown"
            current_content = [line]
        else:
            current_content.append(line)
    
    # Yield last file
    if current_file and current_content:
        content = "\n".join(current_content)
        for sub_chunk in _split_content(content, max_chunk_size):
            yield Chunk(
                content=sub_chunk,
                doc_type="diff",
                file_path=current_file,
                source_url=pr_url,
                chunk_index=chunk_index,
            )
            chunk_index += 1


def chunk_text(
    text: str,
    doc_type: str,
    *,
    source_url: str | None = None,
    max_chunk_size: int = 1500,
    overlap: int = 200,
) -> Iterator[Chunk]:
    """Chunk text with overlap for context preservation.
    
    Args:
        text: Text to chunk.
        doc_type: Document type for the chunks.
        source_url: Optional source URL.
        max_chunk_size: Maximum characters per chunk.
        overlap: Character overlap between chunks.
    
    Yields:
        Chunk objects.
    """
    if len(text) <= max_chunk_size:
        yield Chunk(
            content=text,
            doc_type=doc_type,
            source_url=source_url,
            chunk_index=0,
        )
        return
    
    chunk_index = 0
    start = 0
    
    while start < len(text):
        end = min(start + max_chunk_size, len(text))
        
        # Try to break at paragraph or sentence boundary
        if end < len(text):
            # Look for paragraph break
            para_break = text.rfind("\n\n", start, end)
            if para_break > start + max_chunk_size // 2:
                end = para_break + 2
            else:
                # Look for sentence break
                for punct in [". ", "! ", "? ", "\n"]:
                    sent_break = text.rfind(punct, start + max_chunk_size // 2, end)
                    if sent_break > start:
                        end = sent_break + len(punct)
                        break
        
        yield Chunk(
            content=text[start:end].strip(),
            doc_type=doc_type,
            source_url=source_url,
            chunk_index=chunk_index,
        )
        chunk_index += 1
        
        # Move start with overlap
        start = max(end - overlap, end) if end < len(text) else len(text)


def chunk_code(
    code: str,
    file_path: str,
    *,
    source_url: str | None = None,
    max_chunk_size: int = 1500,
) -> Iterator[Chunk]:
    """Chunk code intelligently by preserving functions/classes.
    
    Args:
        code: Source code text.
        file_path: File path for context.
        source_url: Optional source URL.
        max_chunk_size: Maximum characters per chunk.
    
    Yields:
        Chunk objects.
    """
    lines = code.split("\n")
    current_chunk: list[str] = []
    current_size = 0
    chunk_index = 0
    
    for line in lines:
        line_size = len(line) + 1  # +1 for newline
        
        # Check if adding this line would exceed limit
        if current_size + line_size > max_chunk_size and current_chunk:
            yield Chunk(
                content="\n".join(current_chunk),
                doc_type="code",
                file_path=file_path,
                source_url=source_url,
                chunk_index=chunk_index,
            )
            chunk_index += 1
            current_chunk = []
            current_size = 0
        
        current_chunk.append(line)
        current_size += line_size
    
    # Yield remaining content
    if current_chunk:
        yield Chunk(
            content="\n".join(current_chunk),
            doc_type="code",
            file_path=file_path,
            source_url=source_url,
            chunk_index=chunk_index,
        )


def _split_content(content: str, max_size: int) -> Iterator[str]:
    """Split content into max_size pieces at line boundaries.
    
    Args:
        content: Content to split.
        max_size: Maximum size per piece.
    
    Yields:
        Content pieces.
    """
    if len(content) <= max_size:
        yield content
        return
    
    lines = content.split("\n")
    current_chunk: list[str] = []
    current_size = 0
    
    for line in lines:
        line_size = len(line) + 1
        
        if current_size + line_size > max_size and current_chunk:
            yield "\n".join(current_chunk)
            current_chunk = []
            current_size = 0
        
        current_chunk.append(line)
        current_size += line_size
    
    if current_chunk:
        yield "\n".join(current_chunk)

