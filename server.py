import socket
import os
import datetime
import select
import protocol

HOST = '0.0.0.0'
PORT = 12345
STORAGE_DIR = "server_files"

def main():
    if not os.path.exists(STORAGE_DIR):
        os.makedirs(STORAGE_DIR)

    tcpSock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tcpSock.bind((HOST, PORT))
    tcpSock.listen(1)

    udpSock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udpSock.bind((HOST, PORT))
    protocol.configureUdpBuffer(udpSock)

    print(f"Server listening on {HOST}:{PORT} (TCP and UDP simultaneously)")

    while True:
        try:
            readable, _, _ = select.select([tcpSock, udpSock], [],[])

            for sock in readable:
                if sock == tcpSock:
                    clientSock, addr = tcpSock.accept()
                    print(f"TCP Connected: {addr}")
                    transport = protocol.TcpTransport(clientSock)
                    handleSession(transport, False)
                    clientSock.close()
                elif sock == udpSock:
                    print(f"UDP Packet Received. Processing...")
                    transport = protocol.UdpTransport(udpSock)
                    handleSession(transport, True)

        except KeyboardInterrupt: break
        except Exception as e: print(f"Server loop error: {e}")

    tcpSock.close()
    udpSock.close()

def handleSession(transport, isUdp):
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
                files = os.listdir(STORAGE_DIR)
                fileList = ", ".join(files) if files else "No files on server."
                transport.sendMessage(fileList)
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
                break

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
                chunk = f.read(protocol.CHUNK_SIZE)
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
            cSize = min(protocol.CHUNK_SIZE, remaining)
            data = transport.receiveRawData(cSize)
            f.write(data)
            remaining -= len(data)

    transport.sendMessage("UPLOAD COMPLETE")

if __name__ == "__main__":
    main()
