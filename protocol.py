import socket
import os
import hashlib
import udpProtocol

# Centralized Protocol Constants
CHUNK_SIZE = 1024 * 1024 * 10 # 10MB chunks (for UDP logical windowing)
DISK_CHUNK = 65536           # 64KB chunks (for Disk I/O to prevent RAM overflow)

def configureKeepAlive(sock):
    """
    Configures TCP Keepalive to detect physically disconnected clients.
    Uses OS-specific system calls to set the intervals.
    """
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    if os.name == 'nt':
        # Windows: Enable keepalive, wait 10s, ping every 1s
        sock.ioctl(socket.SIO_KEEPALIVE_VALS, (1, 10000, 1000))
    else:
        # Linux: Idle 10s, ping every 1s, max 5 fails
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 10)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 1)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 5)

def configureUdpBuffer(sock):
    """
    Attempts to expand the OS-level UDP buffer to 8MB.
    This prevents the OS from dropping packets during high-speed transfers.
    """
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8388608)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 8388608)
    except socket.error:
        pass # Silently fallback to default OS buffers if permission is denied

def calculate_checksum(filepath, length):
    """
    Calculates the MD5 checksum of the first 'length' bytes of a file.

    Why: Used during 'Resume' (докачка) to ensure the partial file on disk
    actually matches the file being transferred, preventing file corruption.
    """
    if length == 0 or not os.path.exists(filepath):
        return "0"

    hasher = hashlib.md5()
    remaining = length
    try:
        with open(filepath, 'rb') as f:
            while remaining > 0:
                chunk = f.read(min(DISK_CHUNK, remaining))
                if not chunk: break
                hasher.update(chunk)
                remaining -= len(chunk)
    except IOError:
        return "0"
    return hasher.hexdigest()

class TcpTransport:
    """
    Wraps a raw TCP socket to handle stream fragmentation.
    Buffers incoming bytes and splits them by newline characters (\n).
    """
    def __init__(self, sock):
        self.sock = sock
        self.data = b""
        configureKeepAlive(self.sock)

    def sendMessage(self, message):
        """Encodes and sends a string terminated by a newline."""
        self.sock.sendall((message + "\n").encode('utf-8'))

    def receiveLine(self):
        """
        Reads from the socket until a complete line is formed.
        Keeps remaining bytes in the buffer for the next call.
        """
        while b'\n' not in self.data:
            chunk = self.sock.recv(4096)
            if not chunk: raise ConnectionResetError("Closed by peer")
            self.data += chunk

        # Split exactly at the first newline
        line, self.data = self.data.split(b'\n', 1)
        return line.decode('utf-8').strip()

    def sendRawData(self, data):
        """Sends raw binary data directly over the socket."""
        self.sock.sendall(data)

    def receiveRawData(self, size):
        """
        Receives exactly 'size' bytes from the stream.
        Drains the internal text buffer first before calling recv().
        """
        result = b""
        if len(self.data) > 0:
            take = min(size, len(self.data))
            result = self.data[:take]
            self.data = self.data[take:]

        while len(result) < size:
            chunk = self.sock.recv(min(4096, size - len(result)))
            if not chunk: raise ConnectionResetError("Closed by peer")
            result += chunk
        return result

class UdpTransport:
    """
    Wraps a UDP socket and delegates to our custom Reliability protocol.
    Provides the exact same interface as TcpTransport.
    """
    def __init__(self, sock, targetAddr=None):
        self.sock = sock
        self.targetAddr = targetAddr

    def sendMessage(self, message):
        udpProtocol.sendReliable(self.sock, self.targetAddr, message.encode('utf-8'))

    def receiveLine(self):
        data, addr = udpProtocol.recvReliable(self.sock)
        self.targetAddr = addr # Update peer address for replies
        return data.decode('utf-8')

    def sendRawData(self, data):
        udpProtocol.sendReliable(self.sock, self.targetAddr, data)

    def receiveRawData(self, size):
        data, addr = udpProtocol.recvReliable(self.sock)
        self.targetAddr = addr
        return data
