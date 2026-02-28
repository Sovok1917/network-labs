import socket
import sys
import os
import time
import shutil
import protocol

try:
    import readline
except ImportError:
    pass

DEFAULT_IP = '127.0.0.1'
DEFAULT_PORT = 12345
CLIENT_DIR = "client_files" # Unified directory for both Uploads and Downloads
DISK_CHUNK = 65536

def printHelp():
    print("\n--- Available Commands ---")
    print(f"  Files are stored in: ./{CLIENT_DIR}/")
    print("  HELP, LIST, ECHO <msg>, TIME, UPLOAD <file>, DOWNLOAD <file>, CLOSE")
    print("--------------------------\n")

def drawProgressBar(current, total):
    if total == 0:
        sys.stdout.write("\r[####################] 100% (Empty File)")
        sys.stdout.flush()
        return

    try:
        columns = shutil.get_terminal_size((80, 20)).columns
    except:
        columns = 80

    percent = current / total if total > 0 else 1
    text_part = f" {percent:.1%} ({current}/{total} B)"
    bar_width = max(5, columns - len(text_part) - 3)
    filled = int(bar_width * percent)
    bar = '#' * filled + '-' * (bar_width - filled)

    sys.stdout.write(f"\r[{bar}]{text_part}")
    sys.stdout.flush()

def main():
    # Create the unified directory if it doesn't exist
    if not os.path.exists(CLIENT_DIR):
        os.makedirs(CLIENT_DIR)

    isUdp = '--udp' in sys.argv
    args = [a for a in sys.argv[1:] if a != '--udp']
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
        print("\nClient closed.")

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
    if len(parts) < 2:
        print(f"Usage: UPLOAD <filename> (Must be in '{CLIENT_DIR}/')")
        return

    filename = parts[1]
    filepath = os.path.join(CLIENT_DIR, filename)

    if not os.path.exists(filepath):
        print(f"Error: File '{filename}' not found in '{CLIENT_DIR}/'")
        return

    totalSize = os.path.getsize(filepath)
    transport.sendMessage(f"UPLOAD {filename} {totalSize}")

    # 1. Server replies with what it has: OFFSET <bytes> <checksum>
    response = transport.receiveLine()
    if not response.startswith("OFFSET"): return

    parts = response.split(' ')
    offset = int(parts[1])
    serverChecksum = parts[2] if len(parts) > 2 else "0"

    # 2. Verify Checksum
    if offset > 0:
        localChecksum = protocol.calculate_checksum(filepath, offset)
        if localChecksum != serverChecksum:
            print("Server has different file version. Overwriting...")
            transport.sendMessage("RESTART")
            offset = 0
            if transport.receiveLine() != "READY": return
        else:
            transport.sendMessage("OK") # Matches
            print(f"Resuming upload from {offset}...")
    else:
        transport.sendMessage("OK")

    # 3. Send Data
    if totalSize == 0:
        print("Uploading empty file...")
        print(f"Server: {transport.receiveLine()}")
        return

    startTime = time.time()
    sentBytes = offset

    with open(filepath, 'rb') as f:
        f.seek(offset)
        while True:
            chunk = f.read(DISK_CHUNK)
            if not chunk: break
            transport.sendRawData(chunk)
            sentBytes += len(chunk)
            drawProgressBar(sentBytes, totalSize)

    print()
    calculateBitrate(sentBytes - offset, startTime, time.time())
    print(f"Server: {transport.receiveLine()}")

def performDownload(transport, parts):
    if len(parts) < 2:
        print(f"Usage: DOWNLOAD <filename> (Will save to '{CLIENT_DIR}/')")
        return

    filename = os.path.basename(parts[1])
    localPath = os.path.join(CLIENT_DIR, filename)

    transport.sendMessage(f"DOWNLOAD {filename}")
    response = transport.receiveLine()
    if response.startswith("ERROR"):
        print(f"Server: {response}")
        return

    totalSize = int(response.split(' ')[1])

    # 1. Calculate Local Offset and Checksum
    currentSize = os.path.getsize(localPath) if os.path.exists(localPath) else 0
    if currentSize > totalSize: currentSize = 0

    localChecksum = protocol.calculate_checksum(localPath, currentSize)

    # 2. Send OFFSET request to Server
    transport.sendMessage(f"OFFSET {currentSize} {localChecksum}")

    # 3. Wait for Server Decision
    decision = transport.receiveLine()
    if decision == "RESTART":
        print("Remote file changed. Restarting download...")
        if os.path.exists(localPath): os.remove(localPath)
        transport.sendMessage("OFFSET 0 0") # Request from start
        currentSize = 0
    elif decision != "OK":
        return

    if currentSize > 0:
        print(f"Resuming download from {currentSize}...")

    # 4. Receive Data
    if totalSize == 0:
        open(localPath, 'wb').close()
        print("Downloaded empty file.")
        return

    startTime = time.time()
    receivedBytes = 0
    remaining = totalSize - currentSize

    with open(localPath, 'ab') as f:
        while remaining > 0:
            data = transport.receiveRawData(min(DISK_CHUNK, remaining))
            f.write(data)
            f.flush()
            remaining -= len(data)
            receivedBytes += len(data)
            drawProgressBar(totalSize - remaining, totalSize)

    print()
    calculateBitrate(receivedBytes, startTime, time.time())

def calculateBitrate(bytesTransferred, start, end):
    duration = max(end - start, 0.001)
    mbps = ((bytesTransferred * 8) / 1_000_000) / duration
    print(f"Speed: {mbps:.2f} Mbps")

if __name__ == "__main__":
    main()
