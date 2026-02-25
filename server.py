import socket
import sys
import os
import datetime
import protocol

HOST = '0.0.0.0'
PORT = 12345
STORAGE_DIR = "server_files"
CHUNK_SIZE = 1024 * 1024 # 1MB chunks

def main():
    if not os.path.exists(STORAGE_DIR):
        os.makedirs(STORAGE_DIR)

    isUdp = '--udp' in sys.argv

    if isUdp:
        serverSock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        serverSock.bind((HOST, PORT))
        print(f"UDP Server listening on {HOST}:{PORT}")
        transport = protocol.UdpTransport(serverSock)
        while True:
            try:
                handleSession(transport, True)
            except KeyboardInterrupt: break
            except Exception as e: print(f"Server error: {e}")
    else:
        serverSock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        serverSock.bind((HOST, PORT))
        serverSock.listen(1)
        print(f"TCP Server listening on {HOST}:{PORT}")
        while True:
            try:
                clientSock, addr = serverSock.accept()
                print(f"Connected: {addr}")
                transport = protocol.TcpTransport(clientSock)
                handleSession(transport, False)
                clientSock.close()
            except KeyboardInterrupt: break
            except Exception as e: print(f"Server error: {e}")

    serverSock.close()

def handleSession(transport, isUdp):
    """Processes client commands. UDP handles one interaction at a time."""
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
            elif cmd == 'CLOSE':
                transport.sendMessage("BYE")
                break
            elif cmd == 'DOWNLOAD':
                handleDownload(transport, parts)
            elif cmd == 'UPLOAD':
                handleUpload(transport, parts)
            else:
                transport.sendMessage("UNKNOWN COMMAND")

            if isUdp:
                break # Return to loop to allow other clients

    except ConnectionResetError:
        print("Client disconnected.")

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
                chunk = f.read(CHUNK_SIZE)
                if not chunk: break
                transport.sendRawData(chunk)
    except ValueError: pass

def handleUpload(transport, args):
    if len(args) < 3: return
    filepath = os.path.join(STORAGE_DIR, os.path.basename(args[1]))
    totalSize = int(args[2])

    currentSize = os.path.getsize(filepath) if os.path.exists(filepath) else 0
    if currentSize >= totalSize:
        currentSize = 0
        os.remove(filepath)

    transport.sendMessage(f"OFFSET {currentSize}")

    remaining = totalSize - currentSize
    with open(filepath, 'ab') as f:
        while remaining > 0:
            chunkSize = min(CHUNK_SIZE, remaining)
            data = transport.receiveRawData(chunkSize)
            f.write(data)
            remaining -= len(data)

    transport.sendMessage("UPLOAD COMPLETE")

if __name__ == "__main__":
    main()
