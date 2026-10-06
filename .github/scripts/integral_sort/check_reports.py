"""Fail-closed validation of this source-bound native Surefire regression report."""
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

CLASS = 'com.alibaba.cloud.ai.graph.store.stores.BaseStoreIntegralSortingTest'
METHODS = {
    'memoryStoreSortsIntegralTypesExactly': ({('java.lang.Long', 'java.math.BigInteger')}, 'MemoryStore', 63),
    'fileSystemStoreSortsLongValuesAfterJsonRoundTrip': ({('java.lang.Integer', 'java.lang.Long'), ('java.lang.Long', 'java.lang.Integer')}, 'FileSystemStore', 77),
    'fileSystemStoreSortsBeyondLongRange': ({('java.math.BigInteger', 'java.lang.Long'), ('java.lang.Long', 'java.math.BigInteger')}, 'FileSystemStore', 93),
    'equivalentIntegralValuesUseSecondarySortField': ({('java.lang.Integer', 'java.lang.Byte')}, 'MemoryStore', 107),
    'nullAndMissingValuesKeepTheirOrdering': ({('java.lang.Long', 'java.lang.Integer')}, 'MemoryStore', 119),
    'integralComparatorSatisfiesContract': ({('java.lang.Long', 'java.math.BigInteger')}, None, 150),
}
ERROR_CASES = {f'{method}(boolean)[{index}]': method for method in METHODS for index in (1, 2)}
CONTROLS = {'stringValuesKeepLexicographicOrdering(boolean)[1]', 'stringValuesKeepLexicographicOrdering(boolean)[2]', 'otherComparableTypesKeepTheirBehavior'}
EXPECTED = set(ERROR_CASES) | CONTROLS
FORBIDDEN_OUTCOMES = ('failure', 'skipped', 'flakyFailure', 'flakyError', 'rerunFailure', 'rerunError')


def require(condition, detail):
    if not condition:
        raise ValueError(detail)


def validate_runtime(suite, module):
    properties = {item.get('name'): item.get('value') for item in suite.findall('./properties/property')}
    require(properties.get('java.specification.version') == '17', 'tests did not run on JDK 17')
    classpath = properties.get('surefire.test.class.path', '').split(':')
    require(classpath[:2] == [str(module / 'target/test-classes'), str(module / 'target/classes')], 'not the native module Surefire classpath')
    require(not any('standalone' in value or '/evidence/' in value for value in classpath), 'unexpected standalone or fixture classpath')


def validate(report, mode, started_ns, module):
    report, module = Path(report), Path(module).resolve()
    require(mode in ('baseline', 'candidate'), 'unknown mode')
    require(report.is_file(), 'native Surefire report is missing')
    require(report.stat().st_mtime_ns >= int(started_ns), 'stale native Surefire report')
    suite = ET.parse(report).getroot()
    require(suite.tag == 'testsuite' and suite.get('name') == CLASS, 'wrong native test suite')
    counts = {key: int(suite.attrib[key]) for key in ('tests', 'errors', 'failures', 'skipped')}
    require(counts == {'tests': 15, 'errors': 12 if mode == 'baseline' else 0, 'failures': 0, 'skipped': 0}, f'incorrect counters: {counts}')
    validate_runtime(suite, module)
    cases = suite.findall('testcase')
    names = [case.get('name') for case in cases]
    require(len(names) == 15 and len(set(names)) == 15 and set(names) == EXPECTED, f'incorrect or duplicate case names: {names}')
    require(not any(suite.findall('.//' + tag) for tag in FORBIDDEN_OUTCOMES), 'unexpected failure, skipped, flaky, or rerun node')
    require(len(suite.findall('.//error')) == (12 if mode == 'baseline' else 0), 'unexpected error node count')
    for case in cases:
        name = case.attrib['name']
        require(case.get('classname') == CLASS, 'wrong testcase class')
        errors = case.findall('error')
        should_fail = mode == 'baseline' and name in ERROR_CASES
        require(len(errors) == (1 if should_fail else 0), f'wrong outcome for {name}')
        if not should_fail:
            continue
        method = ERROR_CASES[name]
        pairs, store, line = METHODS[method]
        error = errors[0]
        require(error.get('type') == 'java.lang.ClassCastException', f'wrong exception type in {name}')
        message = error.get('message', '')
        match = re.fullmatch(r"class (java\.(?:lang|math)\.\w+) cannot be cast to class (java\.(?:lang|math)\.\w+) \(\1 and \2 are in module java\.base of loader 'bootstrap'\)", message)
        require(match is not None and match.groups() in pairs, f'wrong ClassCastException message in {name}: {message}')
        stack = error.text or ''
        require(stack.startswith('java.lang.ClassCastException: ' + message), f'wrong stack exception in {name}')
        frames = [
            'com.alibaba.cloud.ai.graph.store.stores.BaseStore.compareByField(BaseStore.java:267)',
            'com.alibaba.cloud.ai.graph.store.stores.BaseStore.lambda$createComparator$0(BaseStore.java:226)',
            f'{CLASS}.{method}(BaseStoreIntegralSortingTest.java:{line})',
        ]
        if store:
            frames.append(f'com.alibaba.cloud.ai.graph.store.stores.{store}.searchItems({store}.java:{119 if store == "MemoryStore" else 159})')
        for frame in frames:
            require(re.search(r'^\s*at ' + re.escape(frame) + r'\s*$', stack, re.MULTILINE), f'missing expected frame {frame} in {name}')
    return counts


def validate_stores(reports, started_ns, module):
    import json
    reports, module = Path(reports), Path(module).resolve()
    expected = json.loads(Path(__file__).with_name('store_cases.json').read_text())
    expected[CLASS] = sorted(EXPECTED)
    actual_files = set(reports.glob('TEST-*.xml'))
    expected_files = {reports / f'TEST-{name}.xml' for name in expected}
    require(actual_files == expected_files, 'wrong or missing native Store suite reports')
    total = 0
    for name, expected_names in expected.items():
        report = reports / f'TEST-{name}.xml'
        if name == CLASS:
            validate(report, 'candidate', started_ns, module)
        else:
            require(report.stat().st_mtime_ns >= int(started_ns), f'stale report: {name}')
            suite = ET.parse(report).getroot()
            require(suite.tag == 'testsuite' and suite.get('name') == name, f'wrong suite: {name}')
            counts = {key: int(suite.attrib[key]) for key in ('tests', 'errors', 'failures', 'skipped')}
            require(counts == {'tests': len(expected_names), 'errors': 0, 'failures': 0, 'skipped': 0}, f'wrong counts: {name}')
            cases = suite.findall('testcase')
            names = [case.get('name') for case in cases]
            require(len(names) == len(expected_names) and len(set(names)) == len(names) and set(names) == set(expected_names), f'wrong or duplicated cases: {name}')
            require(all(case.get('classname') == name for case in cases), f'wrong case class: {name}')
            require(not any(suite.findall('.//' + tag) for tag in ('error', *FORBIDDEN_OUTCOMES)), f'non-green case: {name}')
            validate_runtime(suite, module)
        total += len(expected_names)
    require(total == 70, 'wrong Store suite total')
    return total


if __name__ == '__main__':
    if sys.argv[2] == 'stores':
        result = validate_stores(sys.argv[1], int(sys.argv[3]), sys.argv[4])
    else:
        result = validate(sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4])
    print(f'Strict {sys.argv[2]} report validation passed: {result}')
