# Scripts Directory

This directory contains operational and utility scripts for the ChatWise backend.

## Available Scripts

### Embeddings Management

#### `test_embeddings.py`
Tests embeddings providers to ensure they work correctly.

```bash
# Test current configuration
python scripts/test_embeddings.py

# Test specific provider
python scripts/test_embeddings.py --provider huggingface

# Test all available providers
python scripts/test_embeddings.py --all

# Test specific model
python scripts/test_embeddings.py --provider huggingface --model mixedbread-ai/mxbai-embed-large-v1
```

#### `migrate_embeddings.py`
Migrates knowledge bases between embeddings providers.

```bash
# List all knowledge bases
python scripts/migrate_embeddings.py --list-kbs

# Migrate all KBs to HuggingFace (dry run)
python scripts/migrate_embeddings.py --to-provider huggingface --dry-run

# Migrate specific KB to HuggingFace
python scripts/migrate_embeddings.py --kb-id your-kb-id --to-provider huggingface

# Migrate all KBs back to Cohere
python scripts/migrate_embeddings.py --to-provider cohere

# Verify migration
python scripts/migrate_embeddings.py --verify your-kb-id --to-provider huggingface
```

### Database Migration

#### `apply_knowledge_source_migration.py`
Applies ChromaDB to Supabase migration for knowledge source tracking.

```bash
python scripts/apply_knowledge_source_migration.py
```

## Usage Notes

1. **Environment**: Ensure your `.env` file is properly configured before running scripts
2. **Dependencies**: Install required packages with `pip install -r requirements.txt`
3. **Permissions**: Scripts may need to be made executable with `chmod +x script_name.py`
4. **Backup**: Always backup your data before running migration scripts
5. **Testing**: Use `--dry-run` flags when available to test migrations safely

## Script Development

When creating new scripts:

1. Add proper argument parsing with `argparse`
2. Include comprehensive error handling
3. Provide dry-run options for destructive operations
4. Add progress indicators for long-running operations
5. Include verification steps for migrations
6. Update this README with usage instructions