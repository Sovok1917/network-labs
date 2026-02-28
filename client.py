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
CLIENT_DIR = "client_files"
DISK_CHUNK = 65536

# ANSI Colors for readability
class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

def printError(msg):
    print(f"{Colors.FAIL}[ERROR] {msg}{Colors.ENDC}")

def printSuccess(msg):
    print(f"{Colors.OKGREEN}[SUCCESS] {msg}{Colors.ENDC}")

def printInfo(msg):
    print(f"{Colors.OKBLUE}[INFO] {msg}{Colors.ENDC}")

def printHelp():
    print(f"\n{Colors.HEADER}--- Available Commands ---{Colors.ENDC}")
    print(f"  Files are stored in: {Colors.BOLD}./{CLIENT_DIR}/{Colors.ENDC}")
    print("  HELP, LIST, ECHO <msg>, TIME")
    print("  UPLOAD <file>   - Upload file to server")
    print("  DOWNLOAD <file> - Download file from server")
    print("  CLOSE           - Disconnect and exit")
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

    # Colorize the bar based on completion
    color = Colors.OKBLUE if percent < 1 else Colors.OKGREEN
    sys.stdout.write(f"\r{color}[{bar}]{Colors.ENDC}{text_part}")
    sys.stdout.flush()

def main():
    if not os.path.exists(CLIENT_DIR):
        os.makedirs(CLIENT_DIR)

    isUdp = '--udp' in sys.argv
    args = [a for a in sys.argv[1:] if a != '--udp']
    serverIp = args[0] if len(args) >= 1 else DEFAULT_IP
    serverPort = int(args[1]) if len(args) >= 2 else DEFAULT_PORT

    printInfo(f"Connecting to {serverIp}:{serverPort} (UDP: {isUdp})...")

    sock = None
    try:
        if isUdp:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            protocol.configureUdpBuffer(sock)
            transport = protocol.UdpTransport(sock, (serverIp, serverPort))
        else:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(10) # 10s timeout for connection attempt
            sock.connect((serverIp, serverPort))
            sock.settimeout(None) # Remove timeout for blocking operations
            transport = protocol.TcpTransport(sock)

        printSuccess("Connected!")
        printHelp()

        # --- ROBUST MAIN LOOP ---
        while True:
            try:
                userIn = input("client> ").strip()
                if not userIn: continue

                if userIn.upper() == 'CLOSE':
                    transport.sendMessage("CLOSE")
                    break

                processInput(transport, userIn)

            except KeyboardInterrupt:
                print("\n")
                printInfo("Closing connection...")
                transport.sendMessage("CLOSE")
                break
            except (ConnectionResetError, BrokenPipeError):
                printError("Connection lost to server.")
                break
            except socket.timeout:
                 printError("Operation timed out.")
                 # Don't break, maybe it's temporary
            except Exception as e:
                # Catch logic errors (like file permission) WITHOUT closing connection
                printError(f"Unexpected error: {e}")

    except ConnectionRefusedError:
        printError(f"Could not connect to {serverIp}:{serverPort}. Is the server running?")
    except socket.gaierror:
        printError("Invalid IP address format.")
    except Exception as e:
        printError(f"Fatal startup error: {e}")
    finally:
        if sock: sock.close()
        print(f"{Colors.HEADER}Client Closed.{Colors.ENDC}")

def processInput(transport, userIn):
    parts = userIn.split(' ')
    cmd = parts[0].upper()

    if cmd == 'HELP': printHelp()
    elif cmd == 'UPLOAD': performUpload(transport, parts)
    elif cmd == 'DOWNLOAD': performDownload(transport, parts)
    else:
        # Generic command
        transport.sendMessage(userIn)
        response = transport.receiveLine()
        if response.startswith("ERROR"):
            printError(response)
        else:
            print(f"Server: {response}")

def performUpload(transport, parts):
    if len(parts) < 2:
        printError(f"Usage: UPLOAD <filename>")
        printInfo(f"File must be in: {CLIENT_DIR}")
        return

    filename = parts[1]
    filepath = os.path.join(CLIENT_DIR, filename)

    if not os.path.exists(filepath):
        printError(f"File '{filename}' not found in '{CLIENT_DIR}/'")
        return

    try:
        totalSize = os.path.getsize(filepath)
    except PermissionError:
        printError(f"Permission denied reading '{filename}'")
        return

    transport.sendMessage(f"UPLOAD {filename} {totalSize}")

    response = transport.receiveLine()
    if response.startswith("ERROR"):
        printError(f"Server rejected upload: {response}")
        return
    if not response.startswith("OFFSET"):
        printError(f"Malformed server response: {response}")
        return

    parts = response.split(' ')
    offset = int(parts[1])
    serverChecksum = parts[2] if len(parts) > 2 else "0"

    if offset > 0:
        printInfo(f"Verifying {offset} bytes on server...")
        localChecksum = protocol.calculate_checksum(filepath, offset)
        if localChecksum != serverChecksum:
            print(f"{Colors.WARNING}Checksum mismatch. Restarting upload...{Colors.ENDC}")
            transport.sendMessage("RESTART")
            offset = 0
            if transport.receiveLine() != "READY": return
        else:
            transport.sendMessage("OK")
            printInfo(f"Resuming upload from {offset} bytes")
    else:
        transport.sendMessage("OK")

    if totalSize == 0:
        printInfo("Uploading empty file...")
        print(f"Server: {transport.receiveLine()}")
        return

    startTime = time.time()
    sentBytes = offset

    try:
        with open(filepath, 'rb') as f:
            f.seek(offset)
            while True:
                chunk = f.read(DISK_CHUNK)
                if not chunk: break
                transport.sendRawData(chunk)
                sentBytes += len(chunk)
                drawProgressBar(sentBytes, totalSize)
    except OSError as e:
        printError(f"File read error: {e}")
        return

    print()
    calculateBitrate(sentBytes - offset, startTime, time.time())

    finalMsg = transport.receiveLine()
    if "COMPLETE" in finalMsg:
        printSuccess(finalMsg)
    else:
        print(f"Server: {finalMsg}")

def performDownload(transport, parts):
    if len(parts) < 2:
        printError("Usage: DOWNLOAD <filename>")
        return

    filename = os.path.basename(parts[1])
    localPath = os.path.join(CLIENT_DIR, filename)

    transport.sendMessage(f"DOWNLOAD {filename}")
    response = transport.receiveLine()

    if response.startswith("ERROR"):
        # Nicer formatting for "File Not Found"
        if "not found" in response.lower():
            printError(f"The file '{filename}' does not exist on the server.")
        else:
            printError(f"Server error: {response}")
        return

    try:
        totalSize = int(response.split(' ')[1])
    except (IndexError, ValueError):
        printError(f"Invalid server protocol: {response}")
        return

    currentSize = os.path.getsize(localPath) if os.path.exists(localPath) else 0
    if currentSize > totalSize: currentSize = 0

    localChecksum = protocol.calculate_checksum(localPath, currentSize)
    transport.sendMessage(f"OFFSET {currentSize} {localChecksum}")

    decision = transport.receiveLine()
    if decision == "RESTART":
        print(f"{Colors.WARNING}Remote file changed. Restarting download...{Colors.ENDC}")
        if os.path.exists(localPath): os.remove(localPath)
        transport.sendMessage("OFFSET 0 0")
        currentSize = 0
    elif decision != "OK":
        printError(f"Server negotiation failed: {decision}")
        return

    if currentSize > 0:
        printInfo(f"Resuming download from {currentSize} bytes...")

    if totalSize == 0:
        open(localPath, 'wb').close()
        printSuccess("Downloaded empty file.")
        return

    startTime = time.time()
    receivedBytes = 0
    remaining = totalSize - currentSize

    try:
        with open(localPath, 'ab') as f:
            while remaining > 0:
                data = transport.receiveRawData(min(DISK_CHUNK, remaining))
                f.write(data)
                f.flush()
                remaining -= len(data)
                receivedBytes += len(data)
                drawProgressBar(totalSize - remaining, totalSize)
    except OSError as e:
        printError(f"Disk write error: {e}")
        return

    print()
    calculateBitrate(receivedBytes, startTime, time.time())
    printSuccess("Download complete.")

def calculateBitrate(bytesTransferred, start, end):
    duration = max(end - start, 0.001)
    mbps = ((bytesTransferred * 8) / 1_000_000) / duration
    print(f"Speed: {Colors.BOLD}{mbps:.2f} Mbps{Colors.ENDC}")

if __name__ == "__main__":
    main()
