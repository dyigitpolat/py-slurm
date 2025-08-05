import os
import posixpath
import paramiko
import shlex
from stat import S_ISDIR

class SSHConnection:
    def __init__(self, host, user, port=22, password=None, key_filename=None):
        self.host = host
        self.user = user
        self.port = port
        self.password = password
        self.key_filename = key_filename
        self._client = None
        self._sftp = None

    def connect(self):
        if self._client:
            return self
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            hostname=self.host,
            port=self.port,
            username=self.user,
            password=self.password,
            key_filename=self.key_filename,
            allow_agent=True,
            look_for_keys=True,
            timeout=30,
        )
        transport = client.get_transport()
        if transport is not None:
            transport.set_keepalive(30)
        self._client = client
        self._sftp = client.open_sftp()
        return self

    def close(self):
        try:
            if self._sftp:
                self._sftp.close()
        finally:
            self._sftp = None
        try:
            if self._client:
                self._client.close()
        finally:
            self._client = None

    # ------------- Exec helpers -------------
    def bash(self, command, get_pty=False):
        # Run a command under bash -lc so that PATH and expansions work.
        # Returns (exit_status, stdout_text, stderr_text).
        if not self._client:
            raise RuntimeError("SSHConnection not connected")
        # Use shlex.quote for proper shell escaping instead of fragile string replacement
        cmd = f'bash -lc {shlex.quote(command)}'
        stdin, stdout, stderr = self._client.exec_command(cmd, get_pty=get_pty)
        # Read complete output (but do not automatically echo it).
        out = stdout.read().decode("utf-8", "ignore")
        err = stderr.read().decode("utf-8", "ignore")

        rc = stdout.channel.recv_exit_status()
        return rc, out, err

    def stream_tail(self, remote_file, from_start=False, lines=100):
        # Generator yielding lines as they appear in remote_file using tail -F.
        if not self._client:
            raise RuntimeError("SSHConnection not connected")
        start = "+1" if from_start else str(max(0, int(lines)))
        cmd = f'tail -n {start} -F {remote_file}'
        transport = self._client.get_transport()
        if transport is None:
            raise RuntimeError("No transport")
        channel = transport.open_session()
        channel.get_pty()
        # Use shlex.quote for consistent escaping behavior
        channel.exec_command(f"bash -lc {shlex.quote(cmd)}")
        buff = b""
        try:
            while True:
                if channel.recv_ready():
                    chunk = channel.recv(4096)
                    if not chunk:
                        break
                    buff += chunk
                    while b"\n" in buff:
                        line, buff = buff.split(b"\n", 1)
                        yield line.decode("utf-8", "ignore")
                if channel.exit_status_ready():
                    if buff:
                        yield buff.decode("utf-8", "ignore")
                        buff = b""
                    break
        finally:
            try:
                channel.close()
            except Exception:
                pass

    # ------------- SFTP helpers -------------

    def sftp(self):
        if not self._sftp:
            raise RuntimeError("SFTP session not open")
        return self._sftp

    def exists(self, path):
        try:
            self._sftp.stat(path)
            return True
        except IOError:
            return False

    def isdir(self, path):
        try:
            return S_ISDIR(self._sftp.stat(path).st_mode)
        except IOError:
            return False

    def mkdirs(self, path):
        # posix-style recursive mkdir
        parts = [p for p in path.split('/') if p]
        cur = '/' if path.startswith('/') else ''
        for p in parts:
            cur = posixpath.join(cur, p) if cur else p
            try:
                self._sftp.mkdir(cur)
            except IOError:
                pass  # may already exist

    def put_file(self, local_path, remote_path):
        self.mkdirs(posixpath.dirname(remote_path))
        self._sftp.put(local_path, remote_path)

    def get_file(self, remote_path, local_path):
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        self._sftp.get(remote_path, local_path)

    def put_dir(self, local_dir, remote_dir):
        for root, _, files in os.walk(local_dir):
            for f in files:
                lp = os.path.join(root, f)
                rel = os.path.relpath(lp, local_dir)
                rp = posixpath.join(remote_dir, rel.replace('\\', '/'))
                self.put_file(lp, rp)

    def get_dir(self, remote_dir, local_dir):
        # recursive get using SFTP listings
        def _walk(rdir):
            # yields (rdir, subdirs, files)
            entries = []
            try:
                entries = self._sftp.listdir_attr(rdir)
            except IOError:
                return
            subdirs, files = [], []
            for e in entries:
                name = e.filename
                path = posixpath.join(rdir, name)
                if S_ISDIR(e.st_mode):
                    subdirs.append(name)
                else:
                    files.append(name)
            yield (rdir, subdirs, files)
            for d in subdirs:
                for x in _walk(posixpath.join(rdir, d)):
                    yield x
        for r, _, files in _walk(remote_dir):
            rel = os.path.relpath(r, remote_dir)
            ldir = os.path.join(local_dir, rel if rel != "." else "")
            os.makedirs(ldir, exist_ok=True)
            for f in files:
                self.get_file(posixpath.join(r, f), os.path.join(ldir, f))
