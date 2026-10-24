"""T5 Bridge — serves the team frontend's /api/* contract on top of T4's app.server.

    uvicorn bridge.server:app --host 0.0.0.0 --port 8000

Nothing here is imported at module level that opens a camera, loads a model or binds a port.
"""
