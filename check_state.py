import sys, os
sys.path.insert(0, '/home/abdurrahman/software-engineering-agent')
os.chdir('/home/abdurrahman/software-engineering-agent')

errors = []
ok = []

def check(label, mod):
    try:
        __import__(mod)
        ok.append(label)
    except Exception as e:
        errors.append(f'{label}: {e}')

check('state', 'src.state')
check('models.repo_profile', 'src.models.repo_profile')
check('memory.sqlite_store', 'src.memory.sqlite_store')
check('helpers.embedding.client', 'src.helpers.embedding.client')
check('helpers.repo_discovery', 'src.helpers.repo_discovery')
check('helpers.qdrant.store', 'src.helpers.qdrant.store')
check('helpers.indexer', 'src.helpers.indexer')
check('helpers.symbol_extractor', 'src.helpers.symbol_extractor')
check('helpers.llm', 'src.helpers.llm')
check('nodes.repository_loader', 'src.nodes.repository_loader')
check('nodes.repository_discovery', 'src.nodes.repository_discovery')
check('nodes.code_intelligence', 'src.nodes.code_intelligence')
check('nodes.investigator', 'src.nodes.investigator')
check('nodes.coder', 'src.nodes.coder')
check('nodes.tester', 'src.nodes.tester')
check('graph', 'src.graph')
check('main (fastapi)', 'src.main')

print('=== IMPORT RESULTS ===')
for label in ok:
    print(f'  OK   {label}')
for label in errors:
    print(f'  FAIL {label}')
print(f'\nOK: {len(ok)}, FAIL: {len(errors)}')
