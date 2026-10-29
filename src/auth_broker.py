#!/usr/bin/python3
"""Keep the Polkit caller stable across short-lived GUI and terminal commands."""
import fcntl
import json
import os
from pathlib import Path
import re
import socket
import stat
import struct
import subprocess as sp
import sys

HELPER = '/usr/local/libexec/raze-vpn-control'


def paths():
    runtime = Path('/run/user') / str(os.getuid())
    info = runtime.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise RuntimeError('Unsafe user runtime directory')
    folder = runtime / 'raze-vpn-auth-v2'
    folder.mkdir(mode=0o700, exist_ok=True)
    info = folder.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise RuntimeError('Unsafe VPN authorization directory')
    return folder, str(folder / 'broker.sock')


def valid(args):
    return isinstance(args, list) and (args == ['stop'] or (len(args) == 2 and args[0] in ('start', 'test') and isinstance(args[1], str) and re.fullmatch(r'[A-Za-z0-9_-]{1,64}', args[1]) is not None))


def receive(sock):
    chunks = bytearray()
    while not chunks.endswith(b'\n'):
        chunk = sock.recv(4096)
        if not chunk:
            raise RuntimeError('Authorization broker disconnected')
        chunks.extend(chunk)
        if len(chunks) > 65536:
            raise RuntimeError('Authorization message too large')
    return json.loads(chunks)


def connect():
    folder, address = paths()
    def attempt():
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(180)
        try:
            sock.connect(address)
            return sock
        except OSError:
            sock.close()
            return None
    sock = attempt()
    if sock:
        return sock
    with (folder / 'launch.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        sock = attempt()
        if sock:
            return sock
        import time
        sp.Popen([sys.executable, '-I', str(Path(__file__).resolve()), '--serve'],
                 stdin=sp.DEVNULL, stdout=sp.DEVNULL, stderr=sp.DEVNULL, start_new_session=True)
        for _ in range(40):
            time.sleep(0.05)
            sock = attempt()
            if sock:
                return sock
    raise RuntimeError('Could not start the VPN authorization broker')


def request(args):
    if not valid(args):
        raise RuntimeError('Invalid VPN authorization request')
    with connect() as sock:
        pid, uid, gid = struct.unpack('3i', sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize('3i')))
        if uid != os.getuid():
            raise RuntimeError('Unexpected broker owner')
        sock.sendall(json.dumps(args).encode() + b'\n')
        return receive(sock)


def serve():
    os.umask(0o077)
    folder, address = paths()
    with (folder / 'server.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        Path(address).unlink(missing_ok=True)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(address)
            server.listen(8)
            # No work or memory polling: sleep in accept, exit after 15 minutes idle.
            server.settimeout(900)
            try:
                while True:
                    try:
                        conn, _ = server.accept()
                    except socket.timeout:
                        return
                    with conn:
                        conn.settimeout(180)
                        try:
                            pid, uid, gid = struct.unpack('3i', conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize('3i')))
                            if uid != os.getuid():
                                continue
                            args = receive(conn)
                            if not valid(args):
                                raise RuntimeError('Only VPN start, stop and test requests are accepted')
                            p = sp.run(['/usr/bin/pkexec', HELPER] + args, text=True,
                                       capture_output=True, timeout=150)
                            result = {'returncode': p.returncode, 'stdout': p.stdout, 'stderr': p.stderr}
                        except (RuntimeError, OSError, ValueError, sp.TimeoutExpired) as e:
                            result = {'returncode': 1, 'stdout': '', 'stderr': str(e)}
                        try:
                            conn.sendall(json.dumps(result).encode() + b'\n')
                        except OSError:
                            pass
            finally:
                Path(address).unlink(missing_ok=True)


if __name__ == '__main__':
    if sys.argv[1:] == ['--serve']:
        serve()
