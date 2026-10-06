from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import sys

from check_reports import CLASS, validate, validate_stores
from source_binding import PRODUCTION, TEST, verify

root = Path(sys.argv[1]).resolve()
phase = sys.argv[2]
assert phase in ('baseline', 'focused', 'stores', 'style')
repo = root / ('baseline' if phase == 'baseline' else 'candidate')
module = repo / 'spring-ai-alibaba-graph-core'
target = module / 'target'
evidence = root / 'evidence'
verify(root)
if phase in ('baseline', 'focused'):
    shutil.rmtree(target, ignore_errors=True)
elif phase == 'stores':
    shutil.rmtree(target / 'surefire-reports', ignore_errors=True)
command = [str(repo / 'mvnw'), '-o', '-B', '-ntp', '-s', str(evidence / 'settings.xml'), '-Dmaven.repo.local=' + str(root / 'm2'), '-Dspotless.apply.skip=true', '-pl', 'spring-ai-alibaba-graph-core']
if phase in ('baseline', 'focused'):
    command += ['-Dtest=BaseStoreIntegralSortingTest', 'test']
elif phase == 'stores':
    command += ['-Dtest=BaseStoreIntegralSortingTest,MemoryStoreTest,FileSystemStoreTest,DatabaseStoreTest,DatabaseStoreAllDialectTest,StoreIntegrationTest,GraphStoreIntegrationTest', 'test']
else:
    command += ['checkstyle:check', 'spotless:check']
target.mkdir(parents=True, exist_ok=True)
marker = target / f'.validation-{phase}-started'
with marker.open('x') as stream:
    stream.write(f'{phase} native Maven freshness marker\n')
started_ns = marker.stat().st_mtime_ns
shutil.copy2(marker, evidence / f'{phase}-freshness-marker')
with (evidence / f'{phase}.log').open('w') as log:
    process = subprocess.Popen(command, cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, close_fds=True)
    for line in process.stdout:
        print(line, end='', flush=True)
        log.write(line)
    result = process.wait()
(evidence / f'{phase}-execution.json').write_text(json.dumps({'argv': command, 'started_ns': started_ns, 'freshness_marker': str(marker), 'exit': result}, indent=2))
verify(root)
if phase != 'style':
    report_dir = target / 'surefire-reports'
    destination = evidence / f'{phase}-reports'
    assert not destination.exists(), f'Report destination already exists: {destination}'
    if report_dir.is_dir():
        shutil.copytree(report_dir, destination)
    if phase == 'stores':
        assert result == 0, f'Store suite Maven exit was {result}'
        validate_stores(report_dir, started_ns, module)
    else:
        assert result == (1 if phase == 'baseline' else 0), f'Unexpected Maven exit: {result}'
        report = report_dir / f'TEST-{CLASS}.xml'
        validate(report, 'baseline' if phase == 'baseline' else 'candidate', started_ns, module)
    class_path = 'com/alibaba/cloud/ai/graph/store/stores/BaseStore.class'
    assert (target / 'classes' / class_path).is_file()
    assert not (target / 'test-classes' / class_path).exists(), 'Test stub shadows BaseStore'
    inputs = list((target / 'maven-status').glob('maven-compiler-plugin/compile/*/inputFiles.lst'))
    assert inputs and any(str(repo / PRODUCTION) in path.read_text().splitlines() for path in inputs), 'Native compiler did not compile the pinned BaseStore source'
    test_inputs = list((target / 'maven-status').glob('maven-compiler-plugin/testCompile/*/inputFiles.lst'))
    assert test_inputs and any(str(repo / TEST) in path.read_text().splitlines() for path in test_inputs), 'Native compiler did not compile the submitted regression test'
    shutil.copytree(target / 'maven-status', evidence / f'{phase}-compiler-status')
    (evidence / f'{phase}-class-sha256.json').write_text(json.dumps({class_path: hashlib.sha256((target / 'classes' / class_path).read_bytes()).hexdigest()}, indent=2))
else:
    assert result == 0, f'Style check Maven exit was {result}'
print(f'Validated native Maven phase: {phase}', flush=True)
