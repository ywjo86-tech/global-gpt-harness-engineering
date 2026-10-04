# P3 Canary Execute Specification

The executor accepts exactly one validation registration bound to one fresh P3
Admission. It runs only the fixed P3 validation test set in the exact committed
successor checkout. It creates a result and qualification receipt once.

It grants no generic Full Plan authority and must not switch runtime-current,
start polling, quiesce or stop the predecessor, migrate an existing Run, invoke
a service manager, or mutate unrelated project state. Any identity, digest,
source, test, or create-once conflict fails closed.
