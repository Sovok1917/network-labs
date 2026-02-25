import socket
import struct
import select

PACKET_FORMAT = '!Ic'
HEADER_SIZE = struct.calcsize(PACKET_FORMAT)
PAYLOAD_SIZE = 1400
WINDOW_SIZE = 128
TIMEOUT = 0.05

def sendReliable(sock, targetAddr, data):
    """Sends data reliably using Go-Back-N sliding window."""
    if not data:
        data = b' ' # Prevent logic errors on empty payloads

    chunks = [data[i:i+PAYLOAD_SIZE] for i in range(0, len(data), PAYLOAD_SIZE)]
    total = len(chunks)
    base, nextSeq = 0, 0

    while base < total:
        # Fill the sliding window
        while nextSeq < base + WINDOW_SIZE and nextSeq < total:
            pkt = struct.pack(PACKET_FORMAT, nextSeq, b'D') + chunks[nextSeq]
            sock.sendto(pkt, targetAddr)
            nextSeq += 1

        # Wait for ACKs asynchronously
        r, _, _ = select.select([sock], [],[], TIMEOUT)
        if r:
            base = processAcks(sock, base)
        else:
            nextSeq = base # Timeout: Go-Back-N

    sendFin(sock, targetAddr, total)

def processAcks(sock, currentBase):
    """Reads all available ACKs from socket and updates base."""
    base = currentBase
    while True:
        r, _, _ = select.select([sock], [],[], 0)
        if not r:
            break
        try:
            ackPkt, _ = sock.recvfrom(1024)
            if len(ackPkt) >= HEADER_SIZE:
                ackSeq, pType = struct.unpack(PACKET_FORMAT, ackPkt[:HEADER_SIZE])
                if pType == b'A' and ackSeq >= base:
                    base = ackSeq + 1
        except socket.error:
            break
    return base

def sendFin(sock, targetAddr, total):
    """Sends FIN packet and ensures it is acknowledged."""
    for _ in range(10): # Try up to 10 times
        sock.sendto(struct.pack(PACKET_FORMAT, total, b'F'), targetAddr)
        r, _, _ = select.select([sock], [],[], TIMEOUT)
        if r:
            try:
                ackPkt, _ = sock.recvfrom(1024)
                if len(ackPkt) >= HEADER_SIZE:
                    ackSeq, pType = struct.unpack(PACKET_FORMAT, ackPkt[:HEADER_SIZE])
                    if pType == b'A' and ackSeq == total:
                        return
            except socket.error:
                pass

def recvReliable(sock):
    """Receives data reliably, reassembles chunks, returns (data, addr)."""
    expectedSeq = 0
    result = bytearray()

    while True:
        r, _, _ = select.select([sock], [],[], 10.0)
        if not r:
            raise ConnectionResetError("Timeout waiting for UDP data")

        pkt, addr = sock.recvfrom(2048)
        if len(pkt) < HEADER_SIZE:
            continue

        seq, pType = struct.unpack(PACKET_FORMAT, pkt[:HEADER_SIZE])

        if pType == b'D':
            if seq == expectedSeq:
                result.extend(pkt[HEADER_SIZE:])
                expectedSeq += 1
            # ACK the highest in-order sequence
            ack = struct.pack(PACKET_FORMAT, expectedSeq - 1, b'A')
            sock.sendto(ack, addr)

        elif pType == b'F':
            # ACK the FIN and check if we have all data
            ack = struct.pack(PACKET_FORMAT, seq, b'A')
            sock.sendto(ack, addr)
            if seq == expectedSeq:
                return bytes(result), addr
