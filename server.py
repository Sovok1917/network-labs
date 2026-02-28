import socket
import os
import datetime
import select
import threading
import sys
import protocol

HOST = '0.0.0.0'
PORT = 12345
STORAGE_DIR = "server_files"

def logError(context, error):
    """Extracted exception handler to keep main loops clean."""
    print(f"[ERROR] {context}: {error}")

def initializeSockets():
    """Sets up and binds both TCP and UDP listening sockets."""
    if not os.path.exists(STORAGE_DIR):
        os.makedirs(STORAGE_DIR)

    tcpSock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tcpSock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    tcpSock.bind((HOST, PORT))
    tcpSock.listen(5)

    udpSock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udpSock.bind((HOST, PORT))
    protocol.configureUdpBuffer(udpSock)

    return tcpSock, udpSock

def main():
    """Entry point. Determines mode (Lab 3 Async vs Lab 4 Threaded)."""
    tcpSock, udpSock = initializeSockets()

    if '--async' in sys.argv:
        print(f"Lab 3: ASYNC Server listening on {HOST}:{PORT}")
        runAsyncServer(tcpSock, udpSock)
    else:
        print(f"Lab 4: THREADED Server listening on {HOST}:{PORT}")
        runThreadedServer(tcpSock, udpSock)

# ==========================================
# LAB 4: THREADED SERVER ARCHITECTURE
# ==========================================

def runThreadedServer(tcpSock, udpSock):
    """
    Main loop for Threaded mode.
    Accepts connections and offloads them to individual OS threads.
    """
    while True:
        try:
            r, _, _ = select.select([tcpSock, udpSock], [],[])
            for sock in r:
                if sock == tcpSock:
                    clientSock, addr = tcpSock.accept()
                    print(f"Accepted TCP connection from {addr}")
                    t = threading.Thread(target=threadedClientHandler, args=(clientSock, addr))
                    t.daemon = True
                    t.start()
                elif sock == udpSock:
                    handleUdpPacket(udpSock)
        except KeyboardInterrupt:
            break
        except Exception as e:
            logError("Threaded Main Loop", e)

def threadedClientHandler(sock, addr):
    """Dedicated thread function using blocking I/O."""
    try:
        sock.setblocking(True)
        transport = protocol.TcpTransport(sock)
        while True:
            cmdLine = transport.receiveLine()
            if not cmdLine: break
            processCommandBlocking(transport, cmdLine)
    except Exception as e:
        logError(f"Client {addr}", e)
    finally:
        sock.close()
        print(f"Disconnected: {addr}")

def processCommandBlocking(transport, cmdLine):
    """Executes a single command in blocking threaded mode."""
    parts = cmdLine.split(' ')
    cmd = parts[0].upper()

    if cmd == 'ECHO': transport.sendMessage(" ".join(parts[1:]))
    elif cmd == 'TIME': transport.sendMessage(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    elif cmd == 'LIST': transport.sendMessage(", ".join(os.listdir(STORAGE_DIR)) or "No files")
    elif cmd == 'CLOSE': transport.sendMessage("BYE")
    elif cmd == 'DOWNLOAD': handleDownloadBlocking(transport, parts)
    elif cmd == 'UPLOAD': handleUploadBlocking(transport, parts)
    else: transport.sendMessage("ERROR: Unknown command")

def handleUploadBlocking(transport, parts):
    """Handles upload logic, implementing strict File Collision Blocking."""
    if len(parts) < 3: return

    filepath = os.path.join(STORAGE_DIR, os.path.basename(parts[1]))
    totalSize = int(parts[2])
    currentSize = os.path.getsize(filepath) if os.path.exists(filepath) else 0

    # Complicated Logic Turn: Collision Detection
    # If the file exists fully, or is larger than expected, we hard-block it.
    if currentSize >= totalSize and totalSize > 0:
        transport.sendMessage("ERROR: File completely exists on server. Upload blocked.")
        return

    localChecksum = protocol.calculate_checksum(filepath, currentSize)
    transport.sendMessage(f"OFFSET {currentSize} {localChecksum}")

    decision = transport.receiveLine()
    if decision == "ABORT": return # Client chose to abort due to mismatch

    receiveFileStream(transport, filepath, totalSize - currentSize)

def receiveFileStream(transport, filepath, remaining):
    """Loops and receives binary file data to disk."""
    if remaining == 0:
        open(filepath, 'ab').close()
        transport.sendMessage("UPLOAD COMPLETE")
        return

    with open(filepath, 'ab') as f:
        while remaining > 0:
            data = transport.receiveRawData(min(protocol.DISK_CHUNK, remaining))
            f.write(data)
            f.flush()
            remaining -= len(data)
    transport.sendMessage("UPLOAD COMPLETE")

def handleDownloadBlocking(transport, parts):
    """Handles download logic and file streaming."""
    if len(parts) < 2: return
    filepath = os.path.join(STORAGE_DIR, os.path.basename(parts[1]))

    if not os.path.exists(filepath):
        transport.sendMessage("ERROR: File not found")
        return

    transport.sendMessage(f"SIZE {os.path.getsize(filepath)}")

    response = transport.receiveLine()
    if response == "ABORT": return # Client blocked download
    if not response.startswith("OFFSET"): return

    offset, clientChecksum = parseOffsetResponse(response)

    if offset > 0:
        serverChecksum = protocol.calculate_checksum(filepath, offset)
        if serverChecksum != clientChecksum:
            transport.sendMessage("ABORT") # Force abort on mismatch
            return

    transport.sendMessage("OK")
    sendFileStream(transport, filepath, offset)

def sendFileStream(transport, filepath, offset):
    """Reads a file from disk and pushes it to the socket."""
    with open(filepath, 'rb') as f:
        f.seek(offset)
        while True:
            chunk = f.read(protocol.DISK_CHUNK)
            if not chunk: break
            transport.sendRawData(chunk)

def parseOffsetResponse(response):
    """Extracts offset and checksum safely from protocol string."""
    parts = response.split(' ')
    return int(parts[1]), parts[2] if len(parts) > 2 else "0"

def handleUdpPacket(udpSock):
    """Processes a single stateless UDP packet."""
    try:
        transport = protocol.UdpTransport(udpSock)
        cmdLine = transport.receiveLine()
        processCommandBlocking(transport, cmdLine)
    except Exception as e:
        logError("UDP", e)

# ==========================================
# LAB 3: ASYNC MULTIPLEXED SERVER
# ==========================================

class ClientState:
    """Tracks state for a single asynchronous non-blocking connection."""
    def __init__(self, sock):
        self.sock = sock
        self.state = 'IDLE' # States: IDLE, RECV_UPLOAD, SEND_DOWNLOAD
        self.buffer = b""
        self.send_buffer = b""
        self.file = None
        self.remaining = 0
        self.filename = ""

def runAsyncServer(tcpSock, udpSock):
    """Main loop for Async mode using non-blocking select."""
    tcpSock.setblocking(False)
    inputs, outputs = [tcpSock, udpSock],[]
    clients = {}

    while True:
        try:
            r, w, e = select.select(inputs, outputs, inputs)

            for sock in r:
                if sock == tcpSock:
                    acceptAsyncClient(sock, inputs, clients)
                elif sock == udpSock:
                    handleUdpPacket(udpSock)
                else:
                    handleAsyncRead(sock, inputs, outputs, clients)

            for sock in w:
                if sock in clients: handleAsyncWrite(sock, outputs, clients)

            for sock in e:
                if sock in clients: cleanupAsyncClient(sock, inputs, outputs, clients)

        except KeyboardInterrupt: break
        except Exception as ex: logError("Async Main Loop", ex)

def acceptAsyncClient(tcpSock, inputs, clients):
    """Registers a new non-blocking TCP client."""
    clientSock, _ = tcpSock.accept()
    clientSock.setblocking(False)
    protocol.configureKeepAlive(clientSock)
    inputs.append(clientSock)
    clients[clientSock] = ClientState(clientSock)

def cleanupAsyncClient(sock, inputs, outputs, clients):
    """Safely removes an async client from all lists and closes resources."""
    if sock in inputs: inputs.remove(sock)
    if sock in outputs: outputs.remove(sock)
    if sock in clients:
        if clients[sock].file: clients[sock].file.close()
        del clients[sock]
    sock.close()

def handleAsyncRead(sock, inputs, outputs, clients):
    """Reads chunked data without blocking the global loop."""
    client = clients[sock]
    try:
        data = sock.recv(protocol.DISK_CHUNK)
        if not data:
            cleanupAsyncClient(sock, inputs, outputs, clients)
            return
    except (BlockingIOError, ConnectionResetError): return

    if client.state == 'IDLE':
        client.buffer += data
        while b'\n' in client.buffer:
            line, client.buffer = client.buffer.split(b'\n', 1)
            processAsyncCommand(client, line.decode('utf-8').strip(), outputs)

    elif client.state == 'RECV_UPLOAD':
        client.file.write(data)
        client.file.flush()
        client.remaining -= len(data)
        if client.remaining <= 0:
            client.file.close()
            client.send_buffer += b"UPLOAD COMPLETE\n"
            if sock not in outputs: outputs.append(sock)
            client.state = 'IDLE'

def handleAsyncWrite(sock, outputs, clients):
    """Pushes chunked data to the socket without blocking."""
    client = clients[sock]
    try:
        if client.send_buffer:
            sent = sock.send(client.send_buffer)
            client.send_buffer = client.send_buffer[sent:]

        elif client.state == 'SEND_DOWNLOAD':
            chunk = client.file.read(protocol.DISK_CHUNK)
            if chunk:
                sent = sock.send(chunk)
                if sent < len(chunk):
                    client.file.seek(-(len(chunk) - sent), os.SEEK_CUR)
            else:
                client.file.close()
                client.state = 'IDLE'

        # Unregister from write monitoring if nothing is left to send
        if not client.send_buffer and client.state != 'SEND_DOWNLOAD':
            if sock in outputs: outputs.remove(sock)

    except (BlockingIOError, ConnectionResetError): pass

def processAsyncCommand(client, line, outputs):
    """Parses text commands and updates the state machine asynchronously."""
    parts = line.split(' ')
    cmd = parts[0].upper()

    if cmd == 'ECHO': client.send_buffer += (line[5:] + "\n").encode('utf-8')
    elif cmd == 'TIME': client.send_buffer += (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S") + "\n").encode('utf-8')
    elif cmd == 'LIST': client.send_buffer += (", ".join(os.listdir(STORAGE_DIR)) + "\n").encode('utf-8')
    elif cmd == 'CLOSE': client.send_buffer += b"BYE\n"
    elif cmd == 'UPLOAD': initAsyncUpload(client, parts)
    elif cmd == 'DOWNLOAD': initAsyncDownload(client, parts)
    elif cmd == 'OFFSET': processAsyncOffset(client, parts)
    elif cmd == 'ABORT': client.state = 'IDLE'

    if client.sock not in outputs and (client.send_buffer or client.state == 'SEND_DOWNLOAD'):
        outputs.append(client.sock)

def initAsyncUpload(client, parts):
    """Sets up the state machine for an incoming file."""
    client.filename = os.path.join(STORAGE_DIR, os.path.basename(parts[1]))
    totalSize = int(parts[2])
    cur_sz = os.path.getsize(client.filename) if os.path.exists(client.filename) else 0

    if cur_sz >= totalSize and totalSize > 0:
        client.send_buffer += b"ERROR: File exists\n"
        return

    client.remaining = totalSize - cur_sz
    chk = protocol.calculate_checksum(client.filename, cur_sz)
    client.send_buffer += f"OFFSET {cur_sz} {chk}\n".encode('utf-8')
    client.file = open(client.filename, 'ab')
    client.state = 'RECV_UPLOAD'

def initAsyncDownload(client, parts):
    """Checks file existence and informs client of size."""
    client.filename = os.path.join(STORAGE_DIR, os.path.basename(parts[1]))
    if os.path.exists(client.filename):
        client.send_buffer += f"SIZE {os.path.getsize(client.filename)}\n".encode('utf-8')
    else:
        client.send_buffer += b"ERROR: File not found\n"

def processAsyncOffset(client, parts):
    """Verifies checksums and shifts state to SEND_DOWNLOAD."""
    offset, clientSum = int(parts[1]), parts[2] if len(parts) > 2 else "0"
    if offset > 0 and protocol.calculate_checksum(client.filename, offset) != clientSum:
        client.send_buffer += b"ABORT\n"
        return

    client.send_buffer += b"OK\n"
    client.file = open(client.filename, 'rb')
    client.file.seek(offset)
    client.state = 'SEND_DOWNLOAD'

if __name__ == "__main__":
    main()
