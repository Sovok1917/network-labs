import socket
import sys
import os
import time
import shutil
import protocol

try:
    import readline # Enables bash-like Up-Arrow history on Linux
except ImportError:
    pass

DEFAULT_IP = '127.0.0.1'
DEFAULT_PORT = 12345
CLIENT_DIR = "client_files"
DISK_CHUNK = 65536

class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

def printHelp():
    """Prints the static help menu as explicitly requested."""
    print(f"\n{Colors.HEADER}--- Available Commands ---{Colors.ENDC}")
    print("  HELP, LIST, ECHO <msg>, TIME, UPLOAD <file>, DOWNLOAD <file>, CLOSE")
    print("--------------------------\n")

def printError(msg):
    """Formats and prints error messages in red."""
    print(f"{Colors.FAIL}[ERROR] {msg}{Colors.ENDC}")

def handleConnectionError(e):
    """Extracted exception handler for network dropout events."""
    printError(f"Connection lost or timed out: {e}")
    sys.exit(1)

def handleAppError(e):
    """Extracted exception handler for local OS/App errors (e.g., Disk Full)."""
    printError(f"Local application error: {e}")

def drawProgressBar(current, total):
    """Draws a responsive progress bar in the terminal."""
    if total == 0:
        sys.stdout.write("\r[####################] 100% (Empty File)")
        sys.stdout.flush()
        return

    columns = shutil.get_terminal_size((80, 20)).columns if hasattr(shutil, 'get_terminal_size') else 80
    percent = current / total if total > 0 else 1
    text_part = f" {percent:.1%} ({current}/{total} B)"
    bar_width = max(5, columns - len(text_part) - 3)
    filled = int(bar_width * percent)

    bar = '#' * filled + '-' * (bar_width - filled)
    color = Colors.OKBLUE if percent < 1 else Colors.OKGREEN

    sys.stdout.write(f"\r{color}[{bar}]{Colors.ENDC}{text_part}")
    sys.stdout.flush()

def main():
    """Main client initialization and connection loop."""
    if not os.path.exists(CLIENT_DIR):
        os.makedirs(CLIENT_DIR)

    isUdp = '--udp' in sys.argv
    args = [a for a in sys.argv[1:] if a != '--udp']
    serverIp = args[0] if len(args) >= 1 else DEFAULT_IP
    serverPort = int(args[1]) if len(args) >= 2 else DEFAULT_PORT

    print(f"Connecting to {serverIp}:{serverPort} (UDP: {isUdp})...")

    sock = None
    try:
        sock = initializeSocket(isUdp, serverIp, serverPort)
        transport = protocol.UdpTransport(sock, (serverIp, serverPort)) if isUdp else protocol.TcpTransport(sock)
        print(f"{Colors.OKGREEN}Connected!{Colors.ENDC}")
        printHelp()
        runClientLoop(transport)
    except ConnectionRefusedError:
        printError("Connection refused. Server is offline.")
    except Exception as e:
        handleAppError(e)
    finally:
        if sock: sock.close()
        print("Client closed.")

def initializeSocket(isUdp, ip, port):
    """Creates and configures the socket based on the chosen protocol."""
    if isUdp:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        protocol.configureUdpBuffer(sock)
        return sock
    else:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect((ip, port))
        sock.settimeout(None)
        return sock

def runClientLoop(transport):
    """Main interactive loop for processing user input."""
    while True:
        try:
            userIn = input("client> ").strip()
            if not userIn: continue

            if userIn.upper() == 'CLOSE':
                transport.sendMessage("CLOSE")
                break

            processInput(transport, userIn)
        except (ConnectionResetError, BrokenPipeError, socket.timeout) as e:
            handleConnectionError(e)
        except Exception as e:
            handleAppError(e)

def processInput(transport, userIn):
    """Routes the user command to the appropriate handler function."""
    parts = userIn.split(' ')
    cmd = parts[0].upper()

    if cmd == 'HELP': printHelp()
    elif cmd == 'UPLOAD': performUpload(transport, parts)
    elif cmd == 'DOWNLOAD': performDownload(transport, parts)
    else:
        transport.sendMessage(userIn)
        response = transport.receiveLine()
        if response.startswith("ERROR"): printError(response)
        else: print(f"Server: {response}")

def performUpload(transport, parts):
    """
    Handles file upload, including partial resume and collision prevention.
    Blocks upload if a file with the same name exists but mismatches.
    """
    if len(parts) < 2:
        printError(f"Usage: UPLOAD <filename> (Must be in '{CLIENT_DIR}/')")
        return

    filepath = os.path.join(CLIENT_DIR, parts[1])
    if not os.path.exists(filepath):
        printError("File not found.")
        return

    totalSize = os.path.getsize(filepath)
    transport.sendMessage(f"UPLOAD {parts[1]} {totalSize}")

    response = transport.receiveLine()
    if response.startswith("ERROR"):
        printError(f"Server rejected upload: {response}")
        return

    offset = int(response.split(' ')[1])
    serverChecksum = response.split(' ')[2] if len(response.split(' ')) > 2 else "0"

    # Complicated Logic Turn: Collision Blocker
    # If the server has a partial file, we verify the checksum.
    # If it mismatches, we send ABORT to prevent overwriting/corrupting files safely.
    if offset > 0:
        localChecksum = protocol.calculate_checksum(filepath, offset)
        if localChecksum != serverChecksum:
            printError("Server has a conflicting partial file. Upload blocked.")
            transport.sendMessage("ABORT")
            return
        transport.sendMessage("OK")
        print(f"Resuming upload from {offset} bytes...")
    else:
        transport.sendMessage("OK")

    transmitFileData(transport, filepath, offset, totalSize)

def transmitFileData(transport, filepath, offset, totalSize):
    """Reads a local file and streams it to the server."""
    if totalSize == 0:
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
    """
    Handles file download, including partial resume and collision prevention.
    Blocks download if local file already exists fully or mismatches.
    """
    if len(parts) < 2:
        printError("Usage: DOWNLOAD <filename>")
        return

    filename = os.path.basename(parts[1])
    localPath = os.path.join(CLIENT_DIR, filename)

    transport.sendMessage(f"DOWNLOAD {filename}")
    response = transport.receiveLine()
    if response.startswith("ERROR"):
        printError(response)
        return

    totalSize = int(response.split(' ')[1])
    currentSize = os.path.getsize(localPath) if os.path.exists(localPath) else 0

    # Collision Blocker: Reject if file is completely downloaded
    if currentSize >= totalSize and totalSize > 0:
        printError("File already exists locally in its entirety. Download blocked.")
        transport.sendMessage("ABORT")
        return

    localChecksum = protocol.calculate_checksum(localPath, currentSize)
    transport.sendMessage(f"OFFSET {currentSize} {localChecksum}")

    decision = transport.receiveLine()
    if decision == "ABORT":
        printError("Server blocked resume due to mismatch.")
        return

    receiveFileData(transport, localPath, currentSize, totalSize)

def receiveFileData(transport, localPath, currentSize, totalSize):
    """Receives file stream from server and writes to disk."""
    if totalSize == 0:
        open(localPath, 'wb').close()
        print("Downloaded empty file.")
        return

    print(f"Downloading... Resuming from {currentSize} bytes...")
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
    """Calculates and prints the transfer speed."""
    duration = max(end - start, 0.001)
    mbps = ((bytesTransferred * 8) / 1_000_000) / duration
    print(f"Speed: {Colors.BOLD}{mbps:.2f} Mbps{Colors.ENDC}")

if __name__ == "__main__":
    main()
