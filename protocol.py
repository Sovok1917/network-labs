import socket
import os
import udpProtocol

# Centralized Protocol Constants
CHUNK_SIZE = 1024 * 1024 * 10 # 10MB chunks

def configureKeepAlive(sock):
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    if os.name == 'nt':
        sock.ioctl(socket.SIO_KEEPALIVE_VALS, (1, 10000, 1000))
    else:
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 10)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 1)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 5)

def configureUdpBuffer(sock):
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8388608)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 8388608)
    except socket.error:
        pass

class TcpTransport:
    def __init__(self, sock):
        self.sock = sock
        self.data = b""
        configureKeepAlive(self.sock)

    def sendMessage(self, message):
        self.sock.sendall((message + "\n").encode('utf-8'))

    def receiveLine(self):
        while b'\n' not in self.data:
            chunk = self.sock.recv(4096)
            if not chunk: raise ConnectionResetError("Closed")
            self.data += chunk
        line, self.data = self.data.split(b'\n', 1)
        return line.decode('utf-8').strip()

    def sendRawData(self, data):
        self.sock.sendall(data)

    def receiveRawData(self, size):
        result = b""
        if len(self.data) > 0:
            take = min(size, len(self.data))
            result = self.data[:take]
            self.data = self.data[take:]
        while len(result) < size:
            chunk = self.sock.recv(min(4096, size - len(result)))
            if not chunk: raise ConnectionResetError("Closed")
            result += chunk
        return result

class UdpTransport:
    def __init__(self, sock, targetAddr=None):
        self.sock = sock
        self.targetAddr = targetAddr

    def sendMessage(self, message):
        udpProtocol.sendReliable(self.sock, self.targetAddr, message.encode('utf-8'))

    def receiveLine(self):
        data, addr = udpProtocol.recvReliable(self.sock)
        self.targetAddr = addr
        return data.decode('utf-8')

    def sendRawData(self, data):
        udpProtocol.sendReliable(self.sock, self.targetAddr, data)

    def receiveRawData(self, size):
        data, addr = udpProtocol.recvReliable(self.sock)
        self.targetAddr = addr
        return data
