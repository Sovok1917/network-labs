# net-labs

Implementations for a Network Programming course focusing on socket-level communication and distributed systems.

### Core Rules
*   **Cross-platform:** All code must run on both Arch Linux (Wayland) and Windows 10.
*   **Code Quality:** Functions follow the single responsibility principle: max 60 lines and 10-15 actions per function.
*   **Resilience:** Servers must handle client disconnections gracefully and remain operational without restarts.
*   **Testing:** Designed for execution across 2+ physical or virtual machines in a real network.

### Tech Stack
*   **Language:** Python 3.x
*   **Libraries:** `socket`, `select`, `threading`, `mpi4py`

### Quick Start (Lab 1)
```bash
# Start the server
python server.py

# Start the client
python client.py <server_ip> <port>
```

***

### Why this works:
*   **Direct:** It gets straight to the point.
*   **Commit-friendly:** Since you aren't using a fixed folder structure in the README, it doesn't matter how you organize your branches or commits.
*   **Academic:** It highlights the specific constraints (60 lines/15 actions) that define the project.
