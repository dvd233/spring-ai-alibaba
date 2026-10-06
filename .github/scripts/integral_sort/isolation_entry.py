"""Non-persistent IP network isolation for this audited, limited trusted Store suite."""
from pathlib import Path
import errno
import json
import os
import socket
import subprocess
import sys

root = Path(sys.argv[1]).resolve()
phase = sys.argv[2]
assert phase in ('baseline', 'focused', 'stores', 'style')
for name in os.listdir('/proc/self/fd'):
    if int(name) > 2:
        try:
            os.close(int(name))
        except OSError:
            pass
subprocess.run(['ip', 'link', 'set', 'lo', 'up'], check=True)
links = json.loads(subprocess.check_output(['ip', '-j', 'link', 'show']))
assert {item['ifname'] for item in links} == {'lo'}, links
for family in ('-4', '-6'):
    routes = json.loads(subprocess.check_output(['ip', family, '-j', 'route', 'show', 'table', 'all']))
    assert all(item.get('dev') == 'lo' and 'gateway' not in item and item.get('dst') != 'default' for item in routes), routes
with socket.socket() as listener:
    listener.bind(('127.0.0.1', 0))
    listener.listen(1)
    with socket.create_connection(listener.getsockname(), timeout=1) as client:
        connection, _ = listener.accept()
        with connection:
            client.sendall(b'loopback')
            assert connection.recv(8) == b'loopback'
for family, address in ((socket.AF_INET, ('203.0.113.1', 443)), (socket.AF_INET6, ('2001:db8::1', 443))):
    with socket.socket(family, socket.SOCK_STREAM) as connection:
        connection.settimeout(1)
        result = connection.connect_ex(address)
        assert result == errno.ENETUNREACH, (family, result)
print('IP isolation verified: only lo, loopback works, IPv4/IPv6 TEST-NET egress is unreachable.', flush=True)
print('Scope: trusted limited Store tests; no claim of an adversarial sandbox or Unix-socket isolation.', flush=True)
os.execv(sys.executable, [sys.executable, str(Path(__file__).with_name('run_phase.py')), str(root), phase])
