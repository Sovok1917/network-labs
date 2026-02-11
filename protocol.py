import socket
import os
import struct

class ConnectionBuffer:
    """
    Wrapper class to maintain the buffer state between socket calls.
    """
    def __init__(self):
        self.data = b""

def configureKeepAlive(sock):
    """
    Configures TCP Keepalive parameters for Linux and Windows.
    Args: sock (socket object)
    """
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)

    if os.name == 'nt':
        # Windows: (on, time_ms, interval_ms)
        # Keepalive time: 10 sec, Interval: 1 sec
        sock.ioctl(socket.SIO_KEEPALIVE_VALS, (1, 10000, 1000))
    else:
        # Linux: idle_sec, interval_sec, max_fails
        # Keepalive time: 10 sec, Interval: 1 sec, Max fails: 5
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 10)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 1)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 5)

def sendMessage(sock, message):
    """
    Sends a text message terminated by a newline character.
    Args: sock (socket), message (str)
    """
    try:
        data = (message + "\n").encode('utf-8')
        sock.sendall(data)
    except socket.error as e:
        print(f"Send error: {e}")
        raise

def receiveLine(sock, connBuffer):
    """
    Reads from the socket until a newline character is found.
    Manages an internal buffer to handle TCP stream fragmentation.
    Args: sock (socket), connBuffer (ConnectionBuffer)
    Returns: str (The line without the newline character)
    """
    while b'\n' not in connBuffer.data:
        try:
            chunk = sock.recv(4096)
            if not chunk:
                raise ConnectionResetError("Connection closed by peer")
            connBuffer.data += chunk
        except socket.error as e:
            raise ConnectionResetError(f"Socket error: {e}")

    line, connBuffer.data = connBuffer.data.split(b'\n', 1)
    return line.decode('utf-8').strip()

def sendRawData(sock, data):
    """
    Sends raw binary data to the socket.
    Args: sock (socket), data (bytes)
    """
    sock.sendall(data)

def receiveRawData(sock, size, connBuffer):
    """
    Receives an exact amount of bytes from the socket/buffer.
    Args: sock (socket), size (int), connBuffer (ConnectionBuffer)
    Returns: bytes
    """
    # First, drain the buffer
    data = b""
    if len(connBuffer.data) > 0:
        take = min(size, len(connBuffer.data))
        data = connBuffer.data[:take]
        connBuffer.data = connBuffer.data[take:]

    # Read remaining from socket
    while len(data) < size:
        remaining = size - len(data)
        chunk = sock.recv(min(4096, remaining))
        if not chunk:
            raise ConnectionResetError("Connection closed during transfer")
        data += chunk

    return data
