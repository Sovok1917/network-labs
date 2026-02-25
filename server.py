import socket
import sys
import os
import datetime
import protocol

HOST = '0.0.0.0'
PORT = 12345
STORAGE_DIR = "server_files"

def main():
    """
    Main server loop. Initializes socket and accepts connections sequentially.
    """
    if not os.path.exists(STORAGE_DIR):
        os.makedirs(STORAGE_DIR)

    serverSock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    serverSock.bind((HOST, PORT))
    serverSock.listen(1)
    print(f"Server listening on {HOST}:{PORT}")

    while True:
        try:
            clientSock, addr = serverSock.accept()
            print(f"Connected: {addr}")
            handleClient(clientSock)
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"Server error: {e}")

    serverSock.close()

def handleClient(sock):
    """
    Handles the interaction with a single connected client.
    Args: sock (socket)
    """
    protocol.configureKeepAlive(sock)
    connBuffer = protocol.ConnectionBuffer()

    try:
        while True:
            commandLine = protocol.receiveLine(sock, connBuffer)
            if not commandLine:
                break

            parts = commandLine.split(' ')
            cmd = parts[0].upper()

            if cmd == 'ECHO':
                protocol.sendMessage(sock, " ".join(parts[1:]))
            elif cmd == 'TIME':
                protocol.sendMessage(sock, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            elif cmd == 'CLOSE':
                protocol.sendMessage(sock, "BYE")
                break
            elif cmd == 'DOWNLOAD':
                handleDownload(sock, parts, connBuffer)
            elif cmd == 'UPLOAD':
                handleUpload(sock, parts, connBuffer)
            else:
                protocol.sendMessage(sock, "UNKNOWN COMMAND")

    except (ConnectionResetError, BrokenPipeError):
        print("Client disconnected abruptly.")
    finally:
        sock.close()
        print("Connection closed.")

def handleDownload(sock, args, connBuffer):
    """
    Processes the DOWNLOAD command.
    Protocol:
    1. Server checks file -> Sends SIZE <bytes> or ERROR
    2. Client sends OFFSET <bytes>
    3. Server sends raw bytes in chunks to prevent memory leaks
    """
    if len(args) < 2:
        protocol.sendMessage(sock, "ERROR: Missing filename")
        return

    filename = os.path.basename(args[1])
    filepath = os.path.join(STORAGE_DIR, filename)

    if not os.path.exists(filepath):
        protocol.sendMessage(sock, "ERROR: File not found")
        return

    filesize = os.path.getsize(filepath)
    protocol.sendMessage(sock, f"SIZE {filesize}")

    try:
        response = protocol.receiveLine(sock, connBuffer)
        if not response.startswith("OFFSET"):
            return

        offset = int(response.split(' ')[1])

        with open(filepath, 'rb') as f:
            f.seek(offset)
            while True:
                chunk = f.read(4096)
                if not chunk:
                    break
                protocol.sendRawData(sock, chunk)

    except ValueError:
        print("Invalid offset received")
    except Exception as e:
        print(f"Error during file read/send: {e}")

def handleUpload(sock, args, connBuffer):
    """
    Processes the UPLOAD command.
    Protocol:
    1. Client sends UPLOAD <filename> <total_size>
    2. Server checks partial file -> Sends OFFSET <bytes>
    3. Server receives raw bytes and appends to file
    """
    if len(args) < 3:
        protocol.sendMessage(sock, "ERROR: Usage UPLOAD <filename> <size>")
        return

    filename = os.path.basename(args[1])
    totalSize = int(args[2])
    filepath = os.path.join(STORAGE_DIR, filename)

    currentSize = 0
    if os.path.exists(filepath):
        currentSize = os.path.getsize(filepath)
        # If file is already complete or larger, reset (or handle as error)
        if currentSize >= totalSize:
            currentSize = 0
            os.remove(filepath)

    protocol.sendMessage(sock, f"OFFSET {currentSize}")

    remaining = totalSize - currentSize
    if remaining > 0:
        with open(filepath, 'ab') as f:
            while remaining > 0:
                chunkSize = min(4096, remaining)
                data = protocol.receiveRawData(sock, chunkSize, connBuffer)
                f.write(data)
                remaining -= len(data)

    protocol.sendMessage(sock, "UPLOAD COMPLETE")

if __name__ == "__main__":
    main()
