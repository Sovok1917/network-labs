import socket
import struct
import select

PACKET_FORMAT = '!Ic'
HEADER_SIZE = struct.calcsize(PACKET_FORMAT)
PAYLOAD_SIZE = 1400 # Safe MTU, no fragmentation drops

def sendReliable(sock, targetAddr, data):
    """Radical 'Blast and Patch' sender using Bitmap ACKs."""
    if not data: data = b' '

    # Pre-pack to save CPU time during the firehose loop
    packets = [data[i:i+PAYLOAD_SIZE] for i in range(0, len(data), PAYLOAD_SIZE)]
    total = len(packets)
    unacked = set(range(total))

    sock.setblocking(False)

    while unacked:
        # 1. Firehose Blast: Send all missing packets until OS buffer fills
        for seq in list(unacked):
            pkt = struct.pack(PACKET_FORMAT, seq, b'D') + packets[seq]
            try:
                sock.sendto(pkt, targetAddr)
            except BlockingIOError:
                break # OS Buffer full, pause blasting

        # 2. Ping receiver for the Bitmap ACK
        for _ in range(3):
            try: sock.sendto(struct.pack(PACKET_FORMAT, total, b'F'), targetAddr)
            except BlockingIOError: pass

        # 3. Wait for Bitmap
        r, _, _ = select.select([sock],[],[], 0.05)
        if r:
            try:
                while True:
                    ackPkt, _ = sock.recvfrom(65535)
                    seq, pType = struct.unpack(PACKET_FORMAT, ackPkt[:HEADER_SIZE])
                    if pType == b'A':
                        bitmap = ackPkt[HEADER_SIZE:]
                        toRemove =[]
                        for s in unacked:
                            byteIdx, bitIdx = s // 8, s % 8
                            if byteIdx < len(bitmap) and (bitmap[byteIdx] & (1 << bitIdx)):
                                toRemove.append(s)
                        for s in toRemove: unacked.remove(s)
            except (BlockingIOError, socket.error):
                pass

    sock.setblocking(True)

def recvReliable(sock):
    """Receiver that collects packets and replies with a Bitmap of what it has."""
    resultDict = {}
    totalExpected = -1
    sock.setblocking(False)

    while True:
        r, _, _ = select.select([sock], [],[], 5.0)
        if not r:
            sock.setblocking(True)
            raise ConnectionResetError("Timeout waiting for UDP data")

        try:
            while True:
                pkt, addr = sock.recvfrom(65535)
                if len(pkt) < HEADER_SIZE: continue

                seq, pType = struct.unpack(PACKET_FORMAT, pkt[:HEADER_SIZE])

                if pType == b'D':
                    resultDict[seq] = pkt[HEADER_SIZE:]
                elif pType == b'F':
                    totalExpected = seq

                    if len(resultDict) == totalExpected:
                        # 1. We have everything. Blast final ACKs to be sure.
                        ack = struct.pack(PACKET_FORMAT, totalExpected, b'A') + b'\xff' * ((totalExpected + 7) // 8)
                        for _ in range(10): sock.sendto(ack, addr)
                        sock.setblocking(True)
                        return b''.join(resultDict[i] for i in range(totalExpected)), addr
                    else:
                        # 2. Missing packets. Generate Bitmap and reply.
                        bitmap = bytearray((totalExpected + 7) // 8)
                        for k in resultDict.keys():
                            bitmap[k // 8] |= (1 << (k % 8))
                        ack = struct.pack(PACKET_FORMAT, totalExpected, b'A') + bitmap
                        sock.sendto(ack, addr)
        except (BlockingIOError, socket.error):
            pass
