import socket
import sys
import os
import time
import shutil  # Added for terminal size detection
import protocol

try:
    import readline
except ImportError:
    pass

DEFAULT_IP = '127.0.0.1'
DEFAULT_PORT = 12345
DOWNLOAD_DIR = "client_downloads"
DISK_CHUNK = 65536

def printHelp():
    print("\n--- Available Commands ---")
    print("  HELP, LIST, ECHO <msg>, TIME, UPLOAD <file>, DOWNLOAD <file>, CLOSE")
    print("--------------------------\n")

def drawProgressBar(current, total):
    """
    Draws a responsive progress bar that fits the terminal width.
    """
    try:
        # Get terminal width (default to 80 if fails)
        columns = shutil.get_terminal_size((80, 20)).columns
    except:
        columns = 80

    # Calculate percentage
    percent = current / total if total > 0 else 1

    # Text part: " 100.0% (100MB/100MB)" - roughly 30 chars
    text_part = f" {percent:.1%} ({current}/{total} B)"

    # Calculate remaining space for the bar
    # We subtract len(text_part) and 3 chars for brackets "[] "
    bar_width = max(5, columns - len(text_part) - 3)

    filled = int(bar_width * percent)
    bar = '#' * filled + '-' * (bar_width - filled)

    # Output with carriage return, ensuring no overflow
    sys.stdout.write(f"\r[{bar}]{text_part}")
    sys.stdout.flush()

def main():
    if not os.path.exists(DOWNLOAD_DIR): os.makedirs(DOWNLOAD_DIR)

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
            try:
                userIn = input("client> ").strip()
            except EOFError:
                break

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
    if len(parts) < 2 or not os.path.exists(parts[1]): return

    filename = parts[1]
    totalSize = os.path.getsize(filename)
    transport.sendMessage(f"UPLOAD {os.path.basename(filename)} {totalSize}")

    response = transport.receiveLine()
    if not response.startswith("OFFSET"): return

    offset = int(response.split(' ')[1])
    print(f"Uploading... Resuming from {offset} / {totalSize} bytes")
    startTime = time.time()
    sentBytes = offset

    with open(filename, 'rb') as f:
        f.seek(offset)
        while True:
            chunk = f.read(DISK_CHUNK)
            if not chunk: break
            transport.sendRawData(chunk)
            sentBytes += len(chunk)
            drawProgressBar(sentBytes, totalSize)

    print() # Newline to clear the bar
    calculateBitrate(sentBytes - offset, startTime, time.time())
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
    print(f"Downloading... Resuming from {currentSize} / {totalSize} bytes")
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

    print() # Newline to clear the bar
    calculateBitrate(receivedBytes, startTime, time.time())

def calculateBitrate(bytesTransferred, start, end):
    duration = max(end - start, 0.001)
    mbps = ((bytesTransferred * 8) / 1_000_000) / duration
    print(f"Speed: {mbps:.2f} Mbps")

if __name__ == "__main__":
    main()
