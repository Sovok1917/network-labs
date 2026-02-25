import socket
import sys
import os
import time
import protocol

DEFAULT_IP = '127.0.0.1'
DEFAULT_PORT = 12345
DOWNLOAD_DIR = "client_downloads"

def printHelp():
    """
    Prints a formatted list of all available commands and their usage.
    """
    print("\n--- Available Commands ---")
    print("  HELP                - Show this help message")
    print("  ECHO <message>      - Ask the server to echo the message back")
    print("  TIME                - Get the current time from the server")
    print("  UPLOAD <filename>   - Upload a local file to the server (supports resume)")
    print("  DOWNLOAD <filename> - Download a file from the server (supports resume)")
    print("  CLOSE               - Close the connection and exit")
    print("--------------------------\n")

def main():
    """
    Main client entry point.
    Parses command line arguments for IP and Port.
    """
    if not os.path.exists(DOWNLOAD_DIR):
        os.makedirs(DOWNLOAD_DIR)

    serverIp = DEFAULT_IP
    serverPort = DEFAULT_PORT

    if len(sys.argv) >= 2:
        serverIp = sys.argv[1]

    if len(sys.argv) >= 3:
        try:
            serverPort = int(sys.argv[2])
        except ValueError:
            print("Invalid port number provided. Using default.")

    print(f"Attempting to connect to {serverIp}:{serverPort}...")

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((serverIp, serverPort))
        protocol.configureKeepAlive(sock)

        print(f"Successfully connected to {serverIp}:{serverPort}")
        printHelp()

        connBuffer = protocol.ConnectionBuffer()

        while True:
            try:
                userIn = input("client> ").strip()
            except EOFError:
                break

            if not userIn:
                continue

            if userIn.upper() == 'CLOSE':
                protocol.sendMessage(sock, "CLOSE")
                break

            processInput(sock, userIn, connBuffer)

    except ConnectionRefusedError:
        print(f"Connection refused. Ensure server is running at {serverIp}:{serverPort} and Firewall is open.")
    except socket.gaierror:
        print("Invalid IP address format.")
    except socket.timeout:
        print("Connection timed out.")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        sock.close()
        print("Client closed.")

def processInput(sock, userIn, connBuffer):
    """
    Parses user input and routes to specific handlers.
    Args: sock (socket), userIn (str), connBuffer (ConnectionBuffer)
    """
    parts = userIn.split(' ')
    cmd = parts[0].upper()

    if cmd == 'HELP':
        printHelp()
    elif cmd == 'UPLOAD':
        performUpload(sock, parts, connBuffer)
    elif cmd == 'DOWNLOAD':
        performDownload(sock, parts, connBuffer)
    else:
        protocol.sendMessage(sock, userIn)
        response = protocol.receiveLine(sock, connBuffer)
        print(f"Server: {response}")

def performUpload(sock, parts, connBuffer):
    """
    Handles client-side file upload logic.
    """
    if len(parts) < 2:
        print("Usage: UPLOAD <filename>")
        return

    filename = parts[1]
    if not os.path.exists(filename):
        print("File does not exist.")
        return

    fileSize = os.path.getsize(filename)
    protocol.sendMessage(sock, f"UPLOAD {os.path.basename(filename)} {fileSize}")

    response = protocol.receiveLine(sock, connBuffer)
    if not response.startswith("OFFSET"):
        print(f"Server Error: {response}")
        return

    offset = int(response.split(' ')[1])
    if offset > 0:
        print(f"Resuming upload from byte {offset}...")

    startTime = time.time()

    with open(filename, 'rb') as f:
        f.seek(offset)
        sentBytes = 0
        while True:
            chunk = f.read(4096)
            if not chunk:
                break
            protocol.sendRawData(sock, chunk)
            sentBytes += len(chunk)

    finalMsg = protocol.receiveLine(sock, connBuffer)
    endTime = time.time()

    calculateBitrate(sentBytes, startTime, endTime)
    print(f"Server: {finalMsg}")

def performDownload(sock, parts, connBuffer):
    """
    Handles client-side file download logic.
    """
    if len(parts) < 2:
        print("Usage: DOWNLOAD <filename>")
        return

    filename = os.path.basename(parts[1])
    localPath = os.path.join(DOWNLOAD_DIR, filename)

    protocol.sendMessage(sock, f"DOWNLOAD {filename}")

    response = protocol.receiveLine(sock, connBuffer)
    if response.startswith("ERROR"):
        print(f"Server: {response}")
        return

    totalSize = int(response.split(' ')[1])

    currentSize = 0
    if os.path.exists(localPath):
        currentSize = os.path.getsize(localPath)
        if currentSize >= totalSize:
            print("File already downloaded. Restarting...")
            currentSize = 0
            os.remove(localPath)

    protocol.sendMessage(sock, f"OFFSET {currentSize}")
    print(f"Downloading... Resuming from {currentSize}/{totalSize} bytes")

    startTime = time.time()
    remaining = totalSize - currentSize
    receivedBytes = 0

    with open(localPath, 'ab') as f:
        while remaining > 0:
            chunkSize = min(4096, remaining)
            data = protocol.receiveRawData(sock, chunkSize, connBuffer)
            f.write(data)
            remaining -= len(data)
            receivedBytes += len(data)

    endTime = time.time()
    calculateBitrate(receivedBytes, startTime, endTime)
    print("Download complete.")

def calculateBitrate(bytesTransferred, start, end):
    """
    Calculates and prints the transfer speed.
    """
    duration = end - start
    if duration <= 0:
        duration = 0.001

    bits = bytesTransferred * 8
    mbps = (bits / 1_000_000) / duration
    print(f"Speed: {mbps:.2f} Mbps")

if __name__ == "__main__":
    main()
