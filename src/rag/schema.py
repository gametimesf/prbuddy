"""Weaviate schema definition for PR documents.

Defines the collection schema with multi-tenancy enabled for
PR-scoped isolation.
"""

from __future__ import annotations

import weaviate
from weaviate.classes.config import Configure, Property, DataType, Tokenization
from weaviate.classes.tenants import TenantActivityStatus


SCHEMA_CLASS_NAME = "PRDocument"

# Schema definition for reference
SCHEMA = {
    "class": SCHEMA_CLASS_NAME,
    "multiTenancyConfig": {"enabled": True},
    "vectorizer": "text2vec-openai",
    "moduleConfig": {
        "text2vec-openai": {
            "model": "text-embedding-3-small",
            "type": "text",
        },
        "generative-openai": {},  # For future RAG generation
    },
    "properties": [
        {
            "name": "content",
            "dataType": ["text"],
            "description": "Document content (vectorized)",
        },
        {
            "name": "doc_type",
            "dataType": ["text"],
            "description": "Type: diff|description|author_explanation|issue|doc|comment",
        },
        {
            "name": "file_path",
            "dataType": ["text"],
            "description": "File path for code chunks",
        },
        {
            "name": "source_url",
            "dataType": ["text"],
            "description": "URL to the source (GitHub, Jira, etc.)",
        },
        {
            "name": "chunk_index",
            "dataType": ["int"],
            "description": "Position in the source document",
        },
    ],
}


def create_schema(client: weaviate.WeaviateClient) -> None:
    """Create the PRDocument collection if it doesn't exist.
    
    Args:
        client: Weaviate client.
    """
    # Check if collection exists
    collections = client.collections.list_all()
    if SCHEMA_CLASS_NAME in [c for c in collections]:
        return
    
    # Create collection with multi-tenancy
    client.collections.create(
        name=SCHEMA_CLASS_NAME,
        # Enable multi-tenancy for PR isolation
        multi_tenancy_config=Configure.multi_tenancy(
            enabled=True,
            auto_tenant_creation=True,
            auto_tenant_activation=True,
        ),
        # Use OpenAI for vectorization
        vectorizer_config=Configure.Vectorizer.text2vec_openai(
            model="text-embedding-3-small",
        ),
        # Use OpenAI for generative features
        generative_config=Configure.Generative.openai(),
        # Define properties
        properties=[
            Property(
                name="content",
                data_type=DataType.TEXT,
                description="Document content (vectorized)",
                tokenization=Tokenization.LOWERCASE,
            ),
            Property(
                name="doc_type",
                data_type=DataType.TEXT,
                description="Type: diff|description|author_explanation|issue|doc|comment",
                skip_vectorization=True,
            ),
            Property(
                name="file_path",
                data_type=DataType.TEXT,
                description="File path for code chunks",
                skip_vectorization=True,
            ),
            Property(
                name="source_url",
                data_type=DataType.TEXT,
                description="URL to the source",
                skip_vectorization=True,
            ),
            Property(
                name="chunk_index",
                data_type=DataType.INT,
                description="Position in source document",
                skip_vectorization=True,
            ),
        ],
    )


def ensure_tenant(client: weaviate.WeaviateClient, tenant_name: str) -> None:
    """Ensure a tenant exists for a PR.
    
    Args:
        client: Weaviate client.
        tenant_name: Tenant name (typically owner/repo#number).
    """
    from weaviate.classes.tenants import Tenant
    
    collection = client.collections.get(SCHEMA_CLASS_NAME)
    tenants = collection.tenants.get()
    
    tenant_names = [t.name for t in tenants.values()]
    if tenant_name not in tenant_names:
        collection.tenants.create([Tenant(name=tenant_name)])


def delete_tenant(client: weaviate.WeaviateClient, tenant_name: str) -> bool:
    """Delete a tenant (and all its data).
    
    Args:
        client: Weaviate client.
        tenant_name: Tenant name to delete.
    
    Returns:
        True if deleted, False if not found.
    """
    collection = client.collections.get(SCHEMA_CLASS_NAME)
    tenants = collection.tenants.get()
    
    tenant_names = [t.name for t in tenants.values()]
    if tenant_name not in tenant_names:
        return False
    
    collection.tenants.remove([tenant_name])
    return True


def list_tenants(client: weaviate.WeaviateClient) -> list[str]:
    """List all PR tenants.
    
    Args:
        client: Weaviate client.
    
    Returns:
        List of tenant names.
    """
    collection = client.collections.get(SCHEMA_CLASS_NAME)
    tenants = collection.tenants.get()
    return [t.name for t in tenants.values()]


