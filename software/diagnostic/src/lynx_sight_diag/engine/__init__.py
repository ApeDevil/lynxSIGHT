"""`sight-engine`: the vision engine as a child process of the desktop core.

It speaks the line-delimited JSON protocol defined by the desktop's contract crate
(`contracts/schemas/engine-*.v1.schema.json`) on stdin/stdout and logs to stderr. One request
in, one response out, in order. See `server.py` for the dispatch and `sources.py` for where
feature samples come from (cameras or the synthetic user).
"""
