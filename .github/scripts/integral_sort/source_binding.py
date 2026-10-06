from pathlib import Path
import hashlib
import subprocess

BASE = 'f82da0b50f35744c13968191be2b1cd2452ef550'
CANDIDATE = 'ace6f471d1228fcce2e9b1811e2389b970adf78b'
TREE = 'e1df40ccbc5361a4d888185b2cbba92c163c2d8d'
PRODUCTION = 'spring-ai-alibaba-graph-core/src/main/java/com/alibaba/cloud/ai/graph/store/stores/BaseStore.java'
TEST = 'spring-ai-alibaba-graph-core/src/test/java/com/alibaba/cloud/ai/graph/store/stores/BaseStoreIntegralSortingTest.java'
TEST_SHA256 = 'd89a4d77b402e1850554f0f780a9fc804293ce0e6cfbb8c1eefb46ca64e0130c'


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], text=True).strip()


def verify(root):
    root = Path(root).resolve()
    candidate, baseline = root / 'candidate', root / 'baseline'
    assert git(candidate, 'rev-parse', 'HEAD') == CANDIDATE
    assert git(candidate, 'rev-parse', 'HEAD^{tree}') == TREE
    assert git(candidate, 'rev-parse', 'HEAD^') == BASE
    assert git(baseline, 'rev-parse', 'HEAD') == BASE
    assert set(git(candidate, 'diff-tree', '--no-commit-id', '--name-only', '-r', 'HEAD').splitlines()) == {PRODUCTION, TEST}
    for repo, production_hash in ((baseline, '466de4533ad3f2c537f88492144ae08df9d017fae5bc26a8153b013c3e2a88c6'), (candidate, '5478a2d728026bba00478241d3112f0a517e2688749866968a0d648803ea6ffb')):
        assert hashlib.sha256((repo / PRODUCTION).read_bytes()).hexdigest() == production_hash
        assert hashlib.sha256((repo / TEST).read_bytes()).hexdigest() == TEST_SHA256
        assert git(repo, 'status', '--porcelain', '--untracked-files=no') == '', f'Tracked source was modified: {repo}'
    print('Exact original and reviewed source bindings verified.')
