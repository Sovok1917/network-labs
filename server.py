import socket
import os
import datetime
import select
import threading
import protocol

HOST = '0.0.0.0'
PORT = 12345
STORAGE_DIR = "server_files"

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

    print(f"Threaded Server listening on {HOST}:{PORT}")

    while True:
        try:
            inputs = [tcpSock, udpSock]
            r, _, _ = select.select(inputs, [], [])

            for sock in r:
                if sock == tcpSock:
                    clientSock, addr = tcpSock.accept()
                    print(f"Connected: {addr}")
                    t = threading.Thread(target=handleTcpClient, args=(clientSock, addr))
                    t.daemon = True
                    t.start()

                elif sock == udpSock:
                    transport = protocol.UdpTransport(udpSock)
                    handleSession(transport, True)

        except KeyboardInterrupt: break
        except Exception as ex: print(f"Main Loop Error: {ex}")

    tcpSock.close()
    udpSock.close()

def handleTcpClient(sock, addr):
    try:
        sock.setblocking(True)
        transport = protocol.TcpTransport(sock)
        handleSession(transport, False)
    except Exception as e:
        print(f"Error {addr}: {e}")
    finally:
        sock.close()
        print(f"Disconnected: {addr}")

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
                transport.sendMessage("ERROR: Unknown command")

            if isUdp: break

    except (ConnectionResetError, BrokenPipeError):
        pass

def handleDownload(transport, args):
    if len(args) < 2:
        transport.sendMessage("ERROR: Usage DOWNLOAD <filename>")
        return

    filename = os.path.basename(args[1])
    filepath = os.path.join(STORAGE_DIR, filename)

    if not os.path.exists(filepath):
        transport.sendMessage("ERROR: File not found")
        return

    fileSize = os.path.getsize(filepath)
    transport.sendMessage(f"SIZE {fileSize}")

    try:
        response = transport.receiveLine()
        if not response.startswith("OFFSET"): return

        parts = response.split(' ')
        offset = int(parts[1])
        clientChecksum = parts[2] if len(parts) > 2 else "0"

        if offset > 0:
            serverChecksum = protocol.calculate_checksum(filepath, offset)
            if serverChecksum != clientChecksum:
                transport.sendMessage("RESTART")
                retry = transport.receiveLine()
                if not retry.startswith("OFFSET 0"): return
                offset = 0
            else:
                transport.sendMessage("OK")
        else:
            transport.sendMessage("OK")

        if fileSize == 0: return

        with open(filepath, 'rb') as f:
            f.seek(offset)
            while True:
                chunk = f.read(protocol.DISK_CHUNK)
                if not chunk: break
                transport.sendRawData(chunk)

    except (ValueError, IOError):
        transport.sendMessage("ERROR: Internal server error")

def handleUpload(transport, args):
    if len(args) < 3:
        transport.sendMessage("ERROR: Usage UPLOAD <filename> <size>")
        return

    filename = os.path.basename(args[1])
    filepath = os.path.join(STORAGE_DIR, filename)

    try:
        totalSize = int(args[2])
    except ValueError:
        transport.sendMessage("ERROR: Invalid size")
        return

    currentSize = os.path.getsize(filepath) if os.path.exists(filepath) else 0
    if currentSize > totalSize: currentSize = 0

    localChecksum = protocol.calculate_checksum(filepath, currentSize)
    transport.sendMessage(f"OFFSET {currentSize} {localChecksum}")

    decision = transport.receiveLine()

    if decision == "RESTART":
        currentSize = 0
        if os.path.exists(filepath): os.remove(filepath)
        transport.sendMessage("READY")

    if totalSize == 0:
        open(filepath, 'wb').close()
        transport.sendMessage("UPLOAD COMPLETE")
        return

    remaining = totalSize - currentSize
    with open(filepath, 'ab') as f:
        while remaining > 0:
            cSize = min(protocol.DISK_CHUNK, remaining)
            data = transport.receiveRawData(cSize)
            f.write(data)
            f.flush()
            remaining -= len(data)

    transport.sendMessage("UPLOAD COMPLETE")

if __name__ == "__main__":
    main()
