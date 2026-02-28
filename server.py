import socket
import os
import datetime
import select
import protocol

HOST = '0.0.0.0'
PORT = 12345
STORAGE_DIR = "server_files"
CHUNK_SIZE = 65536 # 64KB chunk ensures instant multiplexing response

class ClientState:
    """Tracks the state machine for a single asynchronous TCP connection."""
    def __init__(self, sock):
        self.sock = sock
        self.state = 'IDLE'
        self.buffer = b""
        self.send_buffer = b""
        self.file = None
        self.remaining = 0
        self.filename = ""

def main():
    if not os.path.exists(STORAGE_DIR):
        os.makedirs(STORAGE_DIR)

    tcpSock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tcpSock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    tcpSock.bind((HOST, PORT))
    tcpSock.listen(5)
    tcpSock.setblocking(False)

    udpSock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udpSock.bind((HOST, PORT))
    protocol.configureUdpBuffer(udpSock)

    inputs = [tcpSock, udpSock]
    outputs =[]
    clients = {}

    print(f"Multiplexed Server listening on {HOST}:{PORT}")

    while True:
        try:
            r, w, e = select.select(inputs, outputs, inputs)

            for sock in r:
                if sock == tcpSock:
                    acceptClient(sock, inputs, clients)
                elif sock == udpSock:
                    handleUdpSession(protocol.UdpTransport(udpSock))
                else:
                    handleRead(sock, inputs, outputs, clients)

            for sock in w:
                if sock in clients:
                    handleWrite(sock, outputs, clients)

            for sock in e:
                if sock in clients:
                    disconnectClient(sock, inputs, outputs, clients)

        except KeyboardInterrupt: break
        except Exception as ex: print(f"Server loop error: {ex}")

    tcpSock.close()
    udpSock.close()

def acceptClient(serverSock, inputs, clients):
    clientSock, addr = serverSock.accept()
    clientSock.setblocking(False)
    protocol.configureKeepAlive(clientSock)
    inputs.append(clientSock)
    clients[clientSock] = ClientState(clientSock)
    print(f"TCP Connected: {addr}")

def disconnectClient(sock, inputs, outputs, clients):
    if sock in inputs: inputs.remove(sock)
    if sock in outputs: outputs.remove(sock)
    if sock in clients:
        if clients[sock].file: clients[sock].file.close()
        del clients[sock]
    sock.close()
    print("Client disconnected.")

def handleRead(sock, inputs, outputs, clients):
    client = clients[sock]
    try:
        data = sock.recv(CHUNK_SIZE)
        if not data:
            disconnectClient(sock, inputs, outputs, clients)
            return
    except (BlockingIOError, ConnectionResetError): return

    if client.state == 'IDLE':
        client.buffer += data
        while b'\n' in client.buffer:
            line, client.buffer = client.buffer.split(b'\n', 1)
            processCmd(client, line.decode('utf-8').strip(), outputs)

    elif client.state == 'RECV_UPLOAD':
        client.file.write(data)
        client.file.flush() # CRITICAL: Pushes the uploaded chunk to disk instantly
        client.remaining -= len(data)
        if client.remaining <= 0:
            client.file.close()
            client.file = None
            client.send_buffer += b"UPLOAD COMPLETE\n"
            if sock not in outputs: outputs.append(sock)
            client.state = 'IDLE'

def handleWrite(sock, outputs, clients):
    client = clients[sock]
    try:
        if client.send_buffer:
            sent = sock.send(client.send_buffer)
            client.send_buffer = client.send_buffer[sent:]

        elif client.state == 'SEND_DOWNLOAD':
            chunk = client.file.read(CHUNK_SIZE)
            if chunk:
                sent = sock.send(chunk)
                if sent < len(chunk):
                    client.file.seek(-(len(chunk) - sent), os.SEEK_CUR)
            else:
                client.file.close()
                client.file = None
                client.state = 'IDLE'
                if sock in outputs: outputs.remove(sock)

        if not client.send_buffer and client.state != 'SEND_DOWNLOAD':
            if sock in outputs: outputs.remove(sock)

    except (BlockingIOError, ConnectionResetError): pass

def processCmd(client, line, outputs):
    parts = line.split(' ')
    cmd = parts[0].upper()

    if cmd == 'ECHO':
        client.send_buffer += (line[5:] + "\n").encode('utf-8')
    elif cmd == 'TIME':
        client.send_buffer += (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S") + "\n").encode('utf-8')
    elif cmd == 'LIST':
        files = ", ".join(os.listdir(STORAGE_DIR)) or "No files"
        client.send_buffer += (files + "\n").encode('utf-8')
    elif cmd == 'UPLOAD' and len(parts) >= 3:
        client.filename = os.path.join(STORAGE_DIR, os.path.basename(parts[1]))
        cur_sz = os.path.getsize(client.filename) if os.path.exists(client.filename) else 0
        client.remaining = int(parts[2]) - cur_sz
        client.send_buffer += f"OFFSET {cur_sz}\n".encode('utf-8')
        client.file = open(client.filename, 'ab')
        client.state = 'RECV_UPLOAD'
    elif cmd == 'DOWNLOAD' and len(parts) >= 2:
        client.filename = os.path.join(STORAGE_DIR, os.path.basename(parts[1]))
        if os.path.exists(client.filename):
            client.send_buffer += f"SIZE {os.path.getsize(client.filename)}\n".encode('utf-8')
        else:
            client.send_buffer += b"ERROR: File not found\n"
    elif cmd == 'OFFSET' and len(parts) >= 2:
        client.file = open(client.filename, 'rb')
        client.file.seek(int(parts[1]))
        client.state = 'SEND_DOWNLOAD'
    elif cmd == 'CLOSE':
        client.send_buffer += b"BYE\n"

    if client.send_buffer or client.state == 'SEND_DOWNLOAD':
        if client.sock not in outputs: outputs.append(client.sock)

def handleUdpSession(transport):
    try:
        commandLine = transport.receiveLine()
        parts = commandLine.split(' ')
        cmd = parts[0].upper()

        if cmd == 'ECHO': transport.sendMessage(" ".join(parts[1:]))
        elif cmd == 'TIME': transport.sendMessage(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        elif cmd == 'LIST': transport.sendMessage(", ".join(os.listdir(STORAGE_DIR)) or "No files")
        elif cmd == 'DOWNLOAD':
            filepath = os.path.join(STORAGE_DIR, os.path.basename(parts[1]))
            if not os.path.exists(filepath):
                transport.sendMessage("ERROR: File not found")
                return
            transport.sendMessage(f"SIZE {os.path.getsize(filepath)}")
            response = transport.receiveLine()
            if response.startswith("OFFSET"):
                with open(filepath, 'rb') as f:
                    f.seek(int(response.split(' ')[1]))
                    while True:
                        chunk = f.read(CHUNK_SIZE)
                        if not chunk: break
                        transport.sendRawData(chunk)
        elif cmd == 'UPLOAD':
            filepath = os.path.join(STORAGE_DIR, os.path.basename(parts[1]))
            curSize = os.path.getsize(filepath) if os.path.exists(filepath) else 0
            if curSize >= int(parts[2]): curSize = 0; os.remove(filepath)
            transport.sendMessage(f"OFFSET {curSize}")
            rem = int(parts[2]) - curSize
            with open(filepath, 'ab') as f:
                while rem > 0:
                    data = transport.receiveRawData(min(CHUNK_SIZE, rem))
                    f.write(data)
                    f.flush()
                    rem -= len(data)
            transport.sendMessage("UPLOAD COMPLETE")
    except Exception as e: print(f"UDP Error: {e}")

if __name__ == "__main__":
    main()
