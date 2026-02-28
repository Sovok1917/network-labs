import socket
import os
import datetime
import select
import threading
import protocol

HOST = '0.0.0.0'
PORT = 12345
STORAGE_DIR = "server_files"
DISK_CHUNK = 65536

def main():
    if not os.path.exists(STORAGE_DIR):
        os.makedirs(STORAGE_DIR)

    tcpSock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tcpSock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    tcpSock.bind((HOST, PORT))
    tcpSock.listen(5)

    udpSock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udpSock.bind((HOST, PORT))
    protocol.configureUdpBuffer(udpSock)

    print(f"Threaded Server (Variant 2) listening on {HOST}:{PORT}")

    # Main Thread: Responsible ONLY for accepting connections
    while True:
        try:
            # We use select to monitor both TCP (for new connections) and UDP
            inputs = [tcpSock, udpSock]
            r, _, _ = select.select(inputs, [], [])

            for sock in r:
                if sock == tcpSock:
                    # New TCP Client -> Spawn a Thread
                    clientSock, addr = tcpSock.accept()
                    print(f"Main Thread: Accepted connection from {addr}")
                    t = threading.Thread(target=handleTcpClient, args=(clientSock, addr))
                    t.daemon = True # Ensures threads close if server exits
                    t.start()

                elif sock == udpSock:
                    # UDP Packet -> Handle in Main Thread (or spawn thread if preferred)
                    # Keeping it simple: UDP is stateless/fast, handle here.
                    transport = protocol.UdpTransport(udpSock)
                    handleSession(transport, True)

        except KeyboardInterrupt: break
        except Exception as ex: print(f"Main Loop Error: {ex}")

    tcpSock.close()
    udpSock.close()

def handleTcpClient(sock, addr):
    """
    Dedicated Thread entry point for a TCP client.
    Uses Blocking I/O for simple linear execution.
    """
    print(f"Thread-{threading.get_ident()}: Started handler for {addr}")
    try:
        # Revert to blocking mode for Threading simplicity
        sock.setblocking(True)
        transport = protocol.TcpTransport(sock)
        handleSession(transport, False)
    except Exception as e:
        print(f"Thread-{threading.get_ident()} Error: {e}")
    finally:
        sock.close()
        print(f"Thread-{threading.get_ident()}: Closed connection {addr}")

def handleSession(transport, isUdp):
    """
    Shared session logic (Blocking style).
    Used by both TCP Threads and UDP Main Loop.
    """
    try:
        while True:
            commandLine = transport.receiveLine()
            if not commandLine: break

            parts = commandLine.split(' ')
            cmd = parts[0].upper()

            if cmd == 'ECHO':
                transport.sendMessage(" ".join(parts[1:]))
            elif cmd == 'TIME':
                transport.sendMessage(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            elif cmd == 'LIST':
                files = ", ".join(os.listdir(STORAGE_DIR)) or "No files"
                transport.sendMessage(files)
            elif cmd == 'CLOSE':
                transport.sendMessage("BYE")
                break
            elif cmd == 'DOWNLOAD':
                handleDownload(transport, parts)
            elif cmd == 'UPLOAD':
                handleUpload(transport, parts)
            else:
                transport.sendMessage("UNKNOWN COMMAND")

            if isUdp: break # UDP is one-shot

    except (ConnectionResetError, BrokenPipeError):
        pass # Normal disconnect

def handleDownload(transport, args):
    if len(args) < 2: return
    filepath = os.path.join(STORAGE_DIR, os.path.basename(args[1]))
    if not os.path.exists(filepath):
        transport.sendMessage("ERROR: File not found")
        return

    transport.sendMessage(f"SIZE {os.path.getsize(filepath)}")
    try:
        response = transport.receiveLine()
        if not response.startswith("OFFSET"): return

        offset = int(response.split(' ')[1])
        with open(filepath, 'rb') as f:
            f.seek(offset)
            while True:
                chunk = f.read(DISK_CHUNK)
                if not chunk: break
                transport.sendRawData(chunk)
    except ValueError: pass

def handleUpload(transport, args):
    if len(args) < 3: return
    filepath = os.path.join(STORAGE_DIR, os.path.basename(args[1]))
    totalSize = int(args[2])

    currentSize = os.path.getsize(filepath) if os.path.exists(filepath) else 0
    if currentSize >= totalSize: currentSize = 0; os.remove(filepath)

    transport.sendMessage(f"OFFSET {currentSize}")
    remaining = totalSize - currentSize
    with open(filepath, 'ab') as f:
        while remaining > 0:
            cSize = min(DISK_CHUNK, remaining)
            data = transport.receiveRawData(cSize)
            f.write(data)
            f.flush() # Ensure atomic write visibility
            remaining -= len(data)

    transport.sendMessage("UPLOAD COMPLETE")

if __name__ == "__main__":
    main()
