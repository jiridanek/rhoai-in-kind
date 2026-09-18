import sys, time
sys.stdout.flush()
t0 = time.time()
print("t=0.0 importing...", flush=True)
from jupyter_client import KernelManager
print("t=%.1f imported" % (time.time() - t0), flush=True)
km = KernelManager(kernel_name="python3")
km.start_kernel()
print("t=%.1f kernel proc started (pid %s)" % (time.time() - t0, km.kernel_id), flush=True)
kc = km.client()
kc.start_channels()
print("t=%.1f channels started; waiting ready (timeout 480s)..." % (time.time() - t0), flush=True)
try:
    kc.wait_for_ready(timeout=480)
    print("t=%.1f KERNEL READY OK" % (time.time() - t0), flush=True)
    kc.stop_channels()
    km.shutdown_kernel(now=True)
    print("t=%.1f CLEANUP OK" % (time.time() - t0), flush=True)
except Exception as e:
    print("t=%.1f WAIT FAILED: %s: %s" % (time.time() - t0, type(e).__name__, e), flush=True)
    try:
        print("kernel proc alive:", km.has_kernel, flush=True)
    except Exception:
        pass
    try:
        km.shutdown_kernel(now=True)
    except Exception:
        pass
