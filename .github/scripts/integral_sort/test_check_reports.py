"""Synthetic positive/negative checks for the validator, not product-test evidence."""
from copy import deepcopy
from pathlib import Path
import os
import tempfile
import unittest
import xml.etree.ElementTree as ET

from check_reports import CLASS, CONTROLS, ERROR_CASES, EXPECTED, METHODS, validate, validate_stores

MODULE = Path('/tmp/native-module')
FIXTURE_TIME_NS = 1_700_000_000_000_000_000


def fixture(mode):
    suite = ET.Element('testsuite', name=CLASS, tests='15', errors='12' if mode == 'baseline' else '0', failures='0', skipped='0')
    properties = ET.SubElement(suite, 'properties')
    ET.SubElement(properties, 'property', name='java.specification.version', value='17')
    ET.SubElement(properties, 'property', name='surefire.test.class.path', value=f'{MODULE}/target/test-classes:{MODULE}/target/classes:/tmp/m2/junit.jar')
    for name in sorted(EXPECTED):
        case = ET.SubElement(suite, 'testcase', name=name, classname=CLASS)
        if mode == 'baseline' and name in ERROR_CASES:
            method = ERROR_CASES[name]
            pairs, store, line = METHODS[method]
            source, target = sorted(pairs)[0]
            message = f"class {source} cannot be cast to class {target} ({source} and {target} are in module java.base of loader 'bootstrap')"
            error = ET.SubElement(case, 'error', type='java.lang.ClassCastException', message=message)
            frames = ['com.alibaba.cloud.ai.graph.store.stores.BaseStore.compareByField(BaseStore.java:267)', 'com.alibaba.cloud.ai.graph.store.stores.BaseStore.lambda$createComparator$0(BaseStore.java:226)', f'{CLASS}.{method}(BaseStoreIntegralSortingTest.java:{line})']
            if store:
                frames.append(f'com.alibaba.cloud.ai.graph.store.stores.{store}.searchItems({store}.java:{119 if store == "MemoryStore" else 159})')
            error.text = 'java.lang.ClassCastException: ' + message + '\n' + ''.join('\tat ' + frame + '\n' for frame in frames)
    return suite


class ValidatorTests(unittest.TestCase):
    def check(self, suite, mode, expect=True, stale=False):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'report.xml'
            start = FIXTURE_TIME_NS
            ET.ElementTree(suite).write(path, encoding='utf-8')
            os.utime(path, ns=(start, start))
            if stale:
                os.utime(path, ns=(start - 10_000_000, start - 10_000_000))
            if expect:
                validate(path, mode, start, MODULE)
            else:
                with self.assertRaises((ValueError, KeyError)):
                    validate(path, mode, start, MODULE)

    def test_accepts_only_expected_baseline_and_candidate(self):
        self.check(fixture('baseline'), 'baseline')
        self.check(fixture('candidate'), 'candidate')

    def test_rejects_missing_extra_duplicate_or_unknown_cases(self):
        for mode in ('baseline', 'candidate'):
            for change in ('missing', 'extra', 'duplicate', 'unknown'):
                with self.subTest(mode=mode, change=change):
                    suite = fixture(mode)
                    cases = suite.findall('testcase')
                    if change == 'missing': suite.remove(cases[-1])
                    if change == 'extra': ET.SubElement(suite, 'testcase', name='unrelated', classname=CLASS)
                    if change == 'duplicate': cases[-1].set('name', cases[0].get('name'))
                    if change == 'unknown': cases[-1].set('name', 'unrelated')
                    self.check(suite, mode, expect=False)

    def test_rejects_extra_failure_even_with_unchanged_counters(self):
        for mode in ('baseline', 'candidate'):
            for tag in ('error', 'failure', 'skipped', 'flakyFailure', 'flakyError', 'rerunFailure', 'rerunError'):
                with self.subTest(mode=mode, tag=tag):
                    suite = fixture(mode)
                    control = next(c for c in suite.findall('testcase') if c.get('name') in CONTROLS)
                    ET.SubElement(control, tag)
                    self.check(suite, mode, expect=False)

    def test_rejects_unexpected_classcast_type_message_or_frames(self):
        for change in ('type', 'message', 'base-frame', 'test-frame', 'store-frame', 'first-line', 'extra-error'):
            with self.subTest(change=change):
                suite = fixture('baseline')
                case = next(c for c in suite.findall('testcase') if c.get('name').startswith('fileSystemStoreSortsLongValuesAfterJsonRoundTrip'))
                error = case.find('error')
                if change == 'type': error.set('type', 'java.lang.AssertionError')
                if change == 'message': error.set('message', 'unrelated ClassCastException')
                if change == 'base-frame': error.text = error.text.replace('BaseStore.java:267', 'BaseStore.java:268')
                if change == 'test-frame': error.text = error.text.replace('fileSystemStoreSortsLongValuesAfterJsonRoundTrip(', 'unrelated(')
                if change == 'store-frame': error.text = error.text.replace('FileSystemStore.searchItems', 'UnrelatedStore.searchItems')
                if change == 'first-line': error.text = 'unrelated\n' + error.text
                if change == 'extra-error': case.append(deepcopy(error))
                self.check(suite, 'baseline', expect=False)

    def test_rejects_wrong_counts_wrong_suite_wrong_class_and_stale_report(self):
        for mode in ('baseline', 'candidate'):
            for change in ('counts', 'suite', 'class', 'stale', 'jdk', 'classpath', 'classpath-tail'):
                with self.subTest(mode=mode, change=change):
                    suite = fixture(mode)
                    if change == 'counts': suite.set('tests', '14')
                    if change == 'suite': suite.set('name', 'UnrelatedTest')
                    if change == 'class': suite.find('testcase').set('classname', 'UnrelatedTest')
                    if change == 'jdk': suite.find('./properties/property').set('value', '21')
                    if change == 'classpath': suite.findall('./properties/property')[1].set('value', '/tmp/standalone/classes')
                    if change == 'classpath-tail':
                        prop = suite.findall('./properties/property')[1]
                        prop.set('value', prop.get('value') + ':/tmp/standalone/classes')
                    self.check(suite, mode, expect=False, stale=change == 'stale')

    def test_rejects_missing_report(self):
        with self.assertRaises(ValueError):
            validate('/nonexistent-native-report.xml', 'baseline', 0, MODULE)

    def test_store_suite_accepts_exact_seventy_and_rejects_mutations(self):
        import json
        expected = json.loads(Path(__file__).with_name('store_cases.json').read_text())
        for mutation in ('none', 'missing-class', 'extra-class', 'duplicate-case', 'missing-case', 'hidden-error', 'flaky-error', 'classpath-tail', 'bad-count', 'stale'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                directory = Path(directory)
                start = FIXTURE_TIME_NS
                focused = directory / f'TEST-{CLASS}.xml'
                ET.ElementTree(fixture('candidate')).write(focused, encoding='utf-8')
                os.utime(focused, ns=(start, start))
                for class_name, methods in expected.items():
                    suite = ET.Element('testsuite', name=class_name, tests=str(len(methods)), errors='0', failures='0', skipped='0')
                    suite.append(deepcopy(fixture('candidate').find('properties')))
                    for method in methods:
                        ET.SubElement(suite, 'testcase', classname=class_name, name=method)
                    report = directory / f'TEST-{class_name}.xml'
                    ET.ElementTree(suite).write(report, encoding='utf-8')
                    os.utime(report, ns=(start, start))
                chosen = directory / ('TEST-' + next(iter(expected)) + '.xml')
                if mutation == 'missing-class': chosen.unlink()
                elif mutation == 'extra-class': (directory / 'TEST-Unrelated.xml').write_text('<testsuite/>')
                elif mutation == 'stale': os.utime(chosen, ns=(start - 10_000_000, start - 10_000_000))
                elif mutation != 'none':
                    suite = ET.parse(chosen).getroot()
                    cases = suite.findall('testcase')
                    if mutation == 'duplicate-case': cases[-1].set('name', cases[0].get('name'))
                    if mutation == 'missing-case': suite.remove(cases[-1])
                    if mutation == 'hidden-error': ET.SubElement(cases[-1], 'error')
                    if mutation == 'flaky-error': ET.SubElement(cases[-1], 'flakyError')
                    if mutation == 'classpath-tail':
                        prop = suite.findall('./properties/property')[1]
                        prop.set('value', prop.get('value') + ':/tmp/standalone/classes')
                    if mutation == 'bad-count': suite.set('tests', '0')
                    ET.ElementTree(suite).write(chosen, encoding='utf-8')
                    os.utime(chosen, ns=(start, start))
                if mutation == 'none': self.assertEqual(validate_stores(directory, start, MODULE), 70)
                else:
                    with self.assertRaises(ValueError): validate_stores(directory, start, MODULE)


if __name__ == '__main__':
    unittest.main(verbosity=2)
