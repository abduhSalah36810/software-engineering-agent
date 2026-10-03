"""Verify all project modules import without error."""

import importlib
import pytest

MODULES = [
    "src.state",
    "src.models",
    "src.models.repo_profile",
    "src.models.assessment",
    "src.memory.sqlite_store",
    "src.helpers.embedding.client",
    "src.helpers.repo_discovery",
    "src.helpers.git_context",
    "src.helpers.repository_assessment",
    "src.helpers.project_stage",
    "src.helpers.incremental_change",
    "src.helpers.affected_dimensions",
    "src.helpers.qdrant.store",
    "src.helpers.indexer",
    "src.helpers.symbol_extractor",
    "src.helpers.llm",
    "src.nodes.repository_loader",
    "src.nodes.repository_discovery",
    "src.nodes.code_intelligence",
    "src.nodes.investigator",
    "src.nodes.coder",
    "src.nodes.tester",
    "src.graph",
    "src.main",
]

@pytest.mark.parametrize("module", MODULES)
def test_module_imports(module):
    importlib.import_module(module)
