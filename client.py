import socket
import sys
import os
import time
import protocol

DEFAULT_IP = '127.0.0.1'
DEFAULT_PORT = 12345
DOWNLOAD_DIR = "client_downloads"
DISK_CHUNK = 65536 # 64KB chunks for real-time disk flushing

def printHelp():
    print("\n--- Available Commands ---")
    print("  HELP, LIST, ECHO <msg>, TIME, UPLOAD <file>, DOWNLOAD <file>, CLOSE")
    print("--------------------------\n")

def main():
    if not os.path.exists(DOWNLOAD_DIR):
        os.makedirs(DOWNLOAD_DIR)

    isUdp = '--udp' in sys.argv
    args =[a for a in sys.argv[1:] if a != '--udp']

    serverIp = args[0] if len(args) >= 1 else DEFAULT_IP
    serverPort = int(args[1]) if len(args) >= 2 else DEFAULT_PORT

    print(f"Connecting to {serverIp}:{serverPort} (UDP: {isUdp})...")

    try:
        if isUdp:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            protocol.configureUdpBuffer(sock)
            transport = protocol.UdpTransport(sock, (serverIp, serverPort))
        else:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect((serverIp, serverPort))
            transport = protocol.TcpTransport(sock)

        printHelp()

        while True:
            try: userIn = input("client> ").strip()
            except EOFError: break
            if not userIn: continue

            if userIn.upper() == 'CLOSE':
                transport.sendMessage("CLOSE")
                break

            processInput(transport, userIn)

    except Exception as e: print(f"Error: {e}")
    finally:
        sock.close()
        print("Client closed.")

def processInput(transport, userIn):
    parts = userIn.split(' ')
    cmd = parts[0].upper()

    if cmd == 'HELP': printHelp()
    elif cmd == 'UPLOAD': performUpload(transport, parts)
    elif cmd == 'DOWNLOAD': performDownload(transport, parts)
    else:
        transport.sendMessage(userIn)
        print(f"Server: {transport.receiveLine()}")

def performUpload(transport, parts):
    if len(parts) < 2 or not os.path.exists(parts[1]): return

    filename = parts[1]
    transport.sendMessage(f"UPLOAD {os.path.basename(filename)} {os.path.getsize(filename)}")

    response = transport.receiveLine()
    if not response.startswith("OFFSET"): return

    offset = int(response.split(' ')[1])
    startTime = time.time()
    sentBytes = 0

    with open(filename, 'rb') as f:
        f.seek(offset)
        while True:
            chunk = f.read(DISK_CHUNK)
            if not chunk: break
            transport.sendRawData(chunk)
            sentBytes += len(chunk)

    endTime = time.time()
    calculateBitrate(sentBytes, startTime, endTime)
    print(f"Server: {transport.receiveLine()}")

def performDownload(transport, parts):
    if len(parts) < 2: return
    localPath = os.path.join(DOWNLOAD_DIR, os.path.basename(parts[1]))

    transport.sendMessage(f"DOWNLOAD {os.path.basename(parts[1])}")
    response = transport.receiveLine()
    if response.startswith("ERROR"): return

    totalSize = int(response.split(' ')[1])
    currentSize = os.path.getsize(localPath) if os.path.exists(localPath) else 0
    if currentSize >= totalSize:
        currentSize = 0
        os.remove(localPath)

    transport.sendMessage(f"OFFSET {currentSize}")
    startTime = time.time()
    receivedBytes, remaining = 0, totalSize - currentSize

    with open(localPath, 'ab') as f:
        while remaining > 0:
            cSize = min(DISK_CHUNK, remaining)
            data = transport.receiveRawData(cSize)
            f.write(data)
            f.flush() # CRITICAL: Force Python to write to the hard drive instantly
            remaining -= len(data)
            receivedBytes += len(data)

    endTime = time.time()
    calculateBitrate(receivedBytes, startTime, endTime)

def calculateBitrate(bytesTransferred, start, end):
    duration = max(end - start, 0.001)
    mbps = ((bytesTransferred * 8) / 1_000_000) / duration
    print(f"Speed: {mbps:.2f} Mbps")

if __name__ == "__main__":
    main()
