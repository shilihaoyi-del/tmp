#!/usr/bin/env python3
import time
path = "/tmp/ttyACM_sc171"
with open(path, "wb", buffering=0) as f:
    n = f.write(b"HELLO_SC171\r\n")
print("wrote", n, "bytes to", path, flush=True)
time.sleep(0.5)
