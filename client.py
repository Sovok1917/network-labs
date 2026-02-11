import socket
import sys
import os
import time
import protocol

SERVER_IP = '127.0.0.1'
PORT = 12345
DOWNLOAD_DIR = "client_downloads"

def main():
    """
    Main client entry point. Connects to server and enters input loop.
    """
    if not os.path.exists(DOWNLOAD_DIR):
        os.makedirs(DOWNLOAD_DIR)

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((SERVER_IP, PORT))
        protocol.configureKeepAlive(sock)
        print(f"Connected to {SERVER_IP}:{PORT}")

        connBuffer = protocol.ConnectionBuffer()

        while True:
            userIn = input("client> ").strip()
            if not userIn:
                continue

            if userIn.upper() == 'CLOSE':
                protocol.sendMessage(sock, "CLOSE")
                break

            processInput(sock, userIn, connBuffer)

    except ConnectionRefusedError:
        print("Could not connect to server.")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        sock.close()

def processInput(sock, userIn, connBuffer):
    """
    Parses user input and routes to specific handlers.
    Args: sock (socket), userIn (str), connBuffer (ConnectionBuffer)
    """
    parts = userIn.split(' ')
    cmd = parts[0].upper()

    if cmd == 'UPLOAD':
        performUpload(sock, parts, connBuffer)
    elif cmd == 'DOWNLOAD':
        performDownload(sock, parts, connBuffer)
    else:
        # Standard text command
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

    # Wait for server to tell us where to resume from
    response = protocol.receiveLine(sock, connBuffer)
    if not response.startswith("OFFSET"):
        print(f"Server Error: {response}")
        return

    offset = int(response.split(' ')[1])
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

    # Wait for final confirmation
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

    # Get file size from server
    response = protocol.receiveLine(sock, connBuffer)
    if response.startswith("ERROR"):
        print(f"Server: {response}")
        return

    totalSize = int(response.split(' ')[1])

    # Check local partial file for resume
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
        duration = 0.001 # Avoid division by zero

    bits = bytesTransferred * 8
    mbps = (bits / 1_000_000) / duration
    print(f"Speed: {mbps:.2f} Mbps")

if __name__ == "__main__":
    main()
